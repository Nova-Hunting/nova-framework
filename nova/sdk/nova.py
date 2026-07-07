"""
Nova SDK Main Class

High-level SDK for Nova prompt pattern matching with policy-based actions.
"""

import functools
import asyncio
import time
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Union, Callable, Any
from pathlib import Path

# Suppress tokenizers parallelism warning when using threading
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from nova.core.matcher import NovaMatcher
from nova.core.parser import NovaParser
from nova.core.rules import NovaRule
from nova.evaluators.llm import get_validated_evaluator, LLMEvaluator
from nova.evaluators.condition import can_llm_change_outcome
from nova.utils.helpers import normalize_unicode

from .policy import NovaPolicy, Action
from .result import ScanResult, RuleMatch
from .redaction import Redactor
from .exceptions import NovaBlockedError, NovaConfigError


class Nova:
    """
    High-level SDK for Nova prompt pattern matching.

    Provides:
    - Policy-based scanning with configurable actions (block/redact/flag/allow)
    - Automatic redaction for matched patterns
    - Decorator for protecting functions
    - Async support
    - Multiple LLM provider support

    Example:
        # First clone the rules: git clone https://github.com/Nova-Hunting/nova-rules
        nova = Nova(
            rules_path="nova-rules/",  # Path to cloned nova-rules repository
            policy={
                "PI": {"action": "block", "severity": "critical"},
                "PII": {"action": "redact"},
                "JB": {"action": "flag"},
            },
            llm_provider="anthropic",
            llm_model="claude-3-sonnet-20240229"
        )

        result = nova.scan(user_prompt)
        if result.blocked:
            return "Request blocked"
        prompt = result.sanitized_text

        # Or use decorator
        @nova.protect(action="block", severity="critical")
        def chat(prompt):
            return openai.chat(prompt)
    """

    def __init__(
        self,
        rules_path: Optional[Union[str, Path, List[str]]] = None,
        rules: Optional[List[NovaRule]] = None,
        policy: Optional[Union[Dict, NovaPolicy]] = None,
        default_action: Action = Action.FLAG,
        llm_provider: Optional[str] = None,
        llm_model: Optional[str] = None,
        redaction_marker: str = "[REDACTED]",
        auto_redact: bool = True,
        on_block: Optional[Callable[["ScanResult"], Any]] = None,
        on_flag: Optional[Callable[["ScanResult"], Any]] = None,
        ignore_invalid_rules: bool = False,
        debug: bool = False,
    ):
        """
        Initialize Nova SDK.

        Args:
            rules_path: Path(s) to .nov rule files or directories
            rules: Pre-loaded NovaRule objects
            policy: Policy configuration (dict or NovaPolicy)
            default_action: Default action when no policy matches
            llm_provider: LLM provider: "openai", "anthropic", "groq", "openrouter", "azure", "ollama"
            llm_model: Specific model override (optional)
            redaction_marker: Text to use for redactions
            auto_redact: Whether to automatically redact on REDACT action
            on_block: Callback when a request is blocked
            on_flag: Callback when a request is flagged
            ignore_invalid_rules: Skip invalid rule files instead of raising NovaConfigError
            debug: Enable debug mode to print detailed match information
        """
        init_start = time.perf_counter()

        self._rules: List[NovaRule] = []
        self._rule_sources: Dict[str, str] = {}  # rule_name → source file path
        self._debug = debug
        self._matchers: Dict[str, NovaMatcher] = {}
        self._llm_evaluator: Optional[LLMEvaluator] = None
        self._llm_provider = llm_provider
        self._llm_model = llm_model
        self._ignore_invalid_rules = ignore_invalid_rules

        # Load rules
        if rules:
            for rule in rules:
                self._append_rule(rule)
        if rules_path:
            self._load_rules(rules_path)

        # Initialize policy
        if isinstance(policy, NovaPolicy):
            self._policy = policy
        elif isinstance(policy, dict):
            self._policy = NovaPolicy(policy, default_action=default_action)
        else:
            self._policy = NovaPolicy(default_action=default_action)

        # Initialize redactor
        self._redactor = Redactor(marker=redaction_marker)
        self._auto_redact = auto_redact

        # Callbacks
        self._on_block = on_block
        self._on_flag = on_flag

        # Initialize evaluators and matchers
        self._initialize_evaluators()
        self._initialize_matchers()

        # Print initialization debug info
        if self._debug:
            init_elapsed = (time.perf_counter() - init_start) * 1000
            self._print_init_debug(init_elapsed)

    def _load_rules(self, rules_path: Union[str, Path, List[str]]) -> None:
        """Load rules from path(s)."""
        paths = [rules_path] if isinstance(rules_path, (str, Path)) else rules_path
        parser = NovaParser()

        for path in paths:
            path = Path(path)
            if path.is_file():
                self._load_rule_file(path, parser)
            elif path.is_dir():
                try:
                    rule_files = sorted(path.rglob("*.nov"))
                except OSError as e:
                    self._handle_rule_load_error(path, f"could not inspect directory: {e}", e)
                    continue
                if not rule_files and not self._ignore_invalid_rules:
                    raise NovaConfigError(f"No .nov rule files found under rules_path: {path}")
                for rule_file in rule_files:
                    self._load_rule_file(rule_file, parser)
            elif not self._ignore_invalid_rules:
                raise NovaConfigError(f"Rules path does not exist or is not readable: {path}")

    def _load_rule_file(self, path: Path, parser: NovaParser) -> None:
        """Load rules from a single file."""
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as e:
            self._handle_rule_load_error(path, f"could not read file: {e}", e)
            return

        # Check if file contains multiple rules
        rule_count = len(re.findall(r'^\s*rule\s+\w+\s*{?', content, flags=re.MULTILINE))
        loaded_before = len(self._rules)
        if rule_count > 1:
            # Parse multiple rules - split by 'rule ' keyword
            rule_blocks = self._split_rule_blocks(content)
            for index, block in enumerate(rule_blocks, start=1):
                if block.strip():
                    try:
                        rule = parser.parse(block)
                        self._append_rule(rule, path)
                    except Exception as e:
                        self._handle_rule_load_error(path, f"rule block #{index} failed to parse: {e}", e)
        else:
            # Single rule
            try:
                rule = parser.parse(content)
                self._append_rule(rule, path)
            except Exception as e:
                self._handle_rule_load_error(path, f"failed to parse rule: {e}", e)

        if len(self._rules) == loaded_before and not self._ignore_invalid_rules:
            raise NovaConfigError(f"No valid rules loaded from {path}")

    def _handle_rule_load_error(self, path: Path, message: str, error: Exception) -> None:
        """Handle rule-loading failures according to strict/ignore mode."""
        if self._ignore_invalid_rules:
            return
        raise NovaConfigError(f"Failed to load rule file {path}: {message}") from error

    def _append_rule(self, rule: NovaRule, source: Optional[Path] = None) -> None:
        """Append a rule while preserving unique rule names."""
        if any(existing.name == rule.name for existing in self._rules):
            raise NovaConfigError(f"Duplicate rule name loaded: {rule.name}")
        self._rules.append(rule)
        if source is not None:
            self._rule_sources[rule.name] = str(source)

    def _split_rule_blocks(self, content: str) -> List[str]:
        """Split content into individual rule blocks."""
        # Split on 'rule' keyword at start of line or after newline
        pattern = r'(?=^\s*rule\s+\w+)'
        blocks = re.split(pattern, content, flags=re.IGNORECASE | re.MULTILINE)
        return [b for b in blocks if b.strip()]

    def _initialize_evaluators(self) -> None:
        """Initialize shared evaluators (semantic, LLM) - load once, share across all matchers."""
        # Check if any rule needs semantic evaluation
        needs_semantic = any(rule.semantics for rule in self._rules)

        if needs_semantic:
            try:
                from nova.evaluators.semantics import DefaultSemanticEvaluator, _EMBEDDING_CACHE
                self._semantic_evaluator = DefaultSemanticEvaluator()
                # Pre-load the model to avoid first-scan delay
                self._semantic_evaluator._load_model()

                # Pre-encode all semantic patterns to avoid first-scan encoding delay
                if self._semantic_evaluator.model is not None:
                    patterns_to_encode = []
                    for rule in self._rules:
                        for pattern in rule.semantics.values():
                            pattern_key = f"{self._semantic_evaluator.model_name}:{pattern.pattern}"
                            if pattern_key not in _EMBEDDING_CACHE:
                                patterns_to_encode.append((pattern_key, pattern.pattern))

                    if patterns_to_encode:
                        # Batch encode all patterns at once for efficiency
                        pattern_texts = [p[1] for p in patterns_to_encode]
                        embeddings = self._semantic_evaluator.model.encode(
                            pattern_texts, convert_to_tensor=True
                        )
                        for i, (key, _) in enumerate(patterns_to_encode):
                            _EMBEDDING_CACHE[key] = embeddings[i:i+1]
            except ImportError:
                self._semantic_evaluator = None
        else:
            self._semantic_evaluator = None

        # Check if any rule needs LLM evaluation
        needs_llm = any(self._rule_needs_llm(rule) for rule in self._rules)

        if needs_llm:
            self._llm_evaluator = self._create_configured_llm_evaluator()

    def _create_configured_llm_evaluator(self) -> Optional[LLMEvaluator]:
        """Create the configured LLM evaluator, preserving fail-closed provider behavior."""
        provider = self._llm_provider or "openai"
        try:
            return get_validated_evaluator(
                provider,
                model=self._llm_model,
                verbose=False
            )
        except ValueError as e:
            if self._llm_provider:
                raise NovaConfigError(f"Failed to initialize LLM evaluator: {e}") from e
            # Preserve historical behavior for default OpenAI: no key means LLM
            # rules fail closed instead of blocking keyword-only use.
            return None

    def _rule_needs_llm(self, rule: NovaRule) -> bool:
        """Check if a rule requires LLM evaluation."""
        if rule.llms:
            return True
        if rule.condition and 'llm.' in rule.condition.lower():
            return True
        return False

    def _redact_keyword_matches(
        self,
        text: str,
        keyword_matches: Dict[str, bool],
        keyword_patterns: Dict[str, Any],
        category: str,
    ):
        """
        Redact keyword matches, falling back to normalized text when matching
        only succeeded after Unicode normalization.
        """
        redaction_result = self._redactor.redact_keywords(
            text,
            keyword_matches,
            keyword_patterns,
            category=category
        )
        if redaction_result.redactions:
            return redaction_result

        normalized_text = normalize_unicode(text)
        if normalized_text == text:
            return redaction_result

        normalized_result = self._redactor.redact_keywords(
            normalized_text,
            keyword_matches,
            keyword_patterns,
            category=category
        )
        for redaction in normalized_result.redactions:
            redaction["normalized"] = True
        return normalized_result

    def _initialize_matchers(self) -> None:
        """Create matchers for all rules, sharing evaluators."""
        for rule in self._rules:
            self._matchers[rule.name] = NovaMatcher(
                rule=rule,
                semantic_evaluator=self._semantic_evaluator,  # Share semantic evaluator
                llm_evaluator=self._llm_evaluator,
                create_llm_evaluator=False  # Don't create new evaluators
            )

    def scan(self, text: str, debug: Optional[bool] = None, parallel: bool = True,
             skip_llm: bool = False) -> ScanResult:
        """
        Scan text against all loaded rules.

        Uses two-phase evaluation for optimal performance:
        1. Fast phase: Evaluate keywords and semantics for ALL rules
        2. LLM phase: Only evaluate LLM patterns if no BLOCK was triggered in fast phase

        Args:
            text: Text to scan
            debug: Override debug mode for this scan (None uses instance setting)
            parallel: Use parallel evaluation for rules with LLM patterns (default True)
            skip_llm: Skip all LLM evaluations for faster scanning (default False).
                      When True, rules that require LLM patterns to match will not match.
                      Use this for high-throughput scenarios where keyword+semantic matching is sufficient.

        Returns:
            ScanResult with all match details and actions
        """
        # Start timing for debug mode
        scan_start_time = time.perf_counter()

        scan_text = normalize_unicode(text)
        matches = []
        sanitized_text = text
        all_redactions = []
        scan_warnings: List[str] = []
        rule_warnings: Dict[str, List[str]] = {}

        # Identify rules that have LLM patterns
        rules_with_llm = set()
        for rule in self._rules:
            if rule.llms or (rule.condition and 'llm.' in rule.condition.lower()):
                rules_with_llm.add(rule.name)

        # PHASE 1: Fast evaluation (keywords + semantics only, no LLM)
        # Create temporary matchers without LLM evaluation for the first pass
        fast_results = []
        early_block = False
        skipped_llm_count = 0

        for rule in self._rules:
            matcher = self._matchers.get(rule.name)
            if not matcher:
                continue

            # For rules with LLM, check if keywords/semantics alone can satisfy the condition
            if rule.name in rules_with_llm:
                result = matcher.check_prompt(scan_text, skip_llm=True)

                if result.get('matched', False):
                    # Rule matched without needing LLM - great!
                    fast_results.append((rule, result))
                    rule_meta = result.get("meta", {})
                    policy_rule = self._policy.get_action_for_match(result["rule_name"], rule_meta)
                    if policy_rule.action == Action.BLOCK:
                        early_block = True
                else:
                    # Rule didn't match yet - may need LLM evaluation later
                    fast_results.append((rule, result))
            else:
                # No LLM patterns - full evaluation is fast
                result = matcher.check_prompt(scan_text)
                if result:
                    fast_results.append((rule, result))
                    if result.get('matched', False):
                        rule_meta = result.get("meta", {})
                        policy_rule = self._policy.get_action_for_match(result["rule_name"], rule_meta)
                        if policy_rule.action == Action.BLOCK:
                            early_block = True

        # PHASE 2: LLM evaluation (only if no BLOCK found and not skipped)
        results = []
        if early_block or skip_llm:
            # Skip all LLM evaluation - we already have a BLOCK or user requested skip
            skipped_llm_count = len(rules_with_llm)
            results = fast_results
        else:
            # Need to run LLM evaluation for rules that require it AND where LLM could change outcome
            rules_needing_llm = []
            for rule, result in fast_results:
                if rule.name in rules_with_llm and not result.get('matched', False):
                    # Use smart condition analysis to determine if LLM could change the outcome
                    debug_info = result.get('debug', {})
                    keyword_matches = debug_info.get('all_keyword_matches', {})
                    semantic_matches = debug_info.get('all_semantic_matches', {})

                    if can_llm_change_outcome(rule.condition, keyword_matches, semantic_matches):
                        rules_needing_llm.append(rule)
                    else:
                        # LLM can't change outcome - skip it
                        skipped_llm_count += 1
                        results.append((rule, result))
                else:
                    results.append((rule, result))

            # Helper to evaluate a single rule with LLM
            def build_llm_worker_failure(rule, error: Exception):
                warning = (
                    f"Rule '{rule.name}' failed closed because SDK LLM evaluation errored: {error}"
                )
                return {
                    "matched": False,
                    "rule_name": rule.name,
                    "meta": rule.meta,
                    "matching_keywords": {},
                    "matching_semantics": {},
                    "matching_llm": {},
                    "semantic_scores": {},
                    "llm_scores": {},
                    "debug": {
                        "condition": rule.condition,
                        "condition_result": False,
                        "evaluation_warnings": [warning],
                        "all_keyword_matches": {},
                        "all_semantic_matches": {},
                        "all_llm_matches": {},
                        "all_llm_details": {},
                    },
                }

            def evaluate_rule_with_llm(rule):
                matcher = self._matchers.get(rule.name)
                if not matcher:
                    return build_llm_worker_failure(rule, RuntimeError("matcher not found"))
                try:
                    return matcher.check_prompt(scan_text)
                except Exception as e:
                    return build_llm_worker_failure(rule, e)

            # Process LLM rules in parallel if enabled and there are multiple
            if parallel and len(rules_needing_llm) > 1:
                max_workers = min(len(rules_needing_llm), 10)
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_to_rule = {
                        executor.submit(evaluate_rule_with_llm, rule): rule
                        for rule in rules_needing_llm
                    }
                    for future in as_completed(future_to_rule):
                        rule = future_to_rule[future]
                        try:
                            result = future.result()
                            if result:
                                results.append((rule, result))
                        except Exception as e:
                            results.append((rule, build_llm_worker_failure(rule, e)))
            else:
                for rule in rules_needing_llm:
                    result = evaluate_rule_with_llm(rule)
                    if result:
                        results.append((rule, result))

        # Process all results
        for rule, result in results:
            warnings = result.get("debug", {}).get("evaluation_warnings", [])
            if warnings:
                rule_warnings.setdefault(rule.name, []).extend(warnings)
                scan_warnings.extend(warnings)

            if not result.get('matched', False):
                continue

            rule_name = result["rule_name"]
            rule_meta = result.get("meta", {})

            # Get policy action for this match
            policy_rule = self._policy.get_action_for_match(rule_name, rule_meta)
            matching_keywords = result.get("matching_keywords", {})
            matching_semantics = result.get("matching_semantics", {})
            matching_llm = result.get("matching_llm", {})
            matched_patterns = [
                *[name for name, matched in matching_keywords.items() if matched],
                *[name for name, matched in matching_semantics.items() if matched],
                *[name for name, matched in matching_llm.items() if matched],
            ]

            # Create RuleMatch
            match = RuleMatch(
                rule_name=rule_name,
                meta=rule_meta,
                action=policy_rule.action,
                severity=rule_meta.get("severity"),
                source_file=self._rule_sources.get(rule_name),
                matching_keywords=matching_keywords,
                matching_semantics=matching_semantics,
                matching_llm=matching_llm,
                semantic_scores=result.get("semantic_scores", {}),
                llm_scores=result.get("llm_scores", {}),
                matched_patterns=matched_patterns,
            )
            matches.append(match)

            # Handle redaction if needed
            if policy_rule.action == Action.REDACT and self._auto_redact:
                if match.matching_keywords:
                    redaction_result = self._redact_keyword_matches(
                        sanitized_text,
                        match.matching_keywords,
                        rule.keywords,
                        category=rule_meta.get("category", "redacted")
                    )
                    sanitized_text = redaction_result.text
                    all_redactions.extend(redaction_result.redactions)

            # Execute callback if defined in policy
            if policy_rule.callback:
                policy_rule.callback(match)

        # Create result
        scan_result = ScanResult(
            original_text=text,
            sanitized_text=sanitized_text,
            matches=matches,
            redactions=all_redactions,
            warnings=scan_warnings,
            rule_warnings=rule_warnings
        )

        # Execute global callbacks
        if scan_result.blocked and self._on_block:
            self._on_block(scan_result)
        elif scan_result.flagged and self._on_flag:
            self._on_flag(scan_result)

        # Debug output
        if debug or (debug is None and self._debug):
            scan_elapsed_ms = (time.perf_counter() - scan_start_time) * 1000
            fast_count = len(self._rules) - len(rules_with_llm)
            llm_count = len(rules_with_llm)
            if skip_llm:
                skip_reason = "skip_llm=True"
            elif early_block:
                skip_reason = "early BLOCK"
            elif skipped_llm_count > 0:
                skip_reason = "condition analysis"
            else:
                skip_reason = ""
            self._print_debug(text, scan_result, scan_elapsed_ms, fast_count, llm_count, skipped_llm_count, skip_reason)

        return scan_result

    async def scan_async(self, text: str) -> ScanResult:
        """
        Async version of scan.

        Runs the synchronous scan in a thread pool executor.

        Args:
            text: Text to scan

        Returns:
            ScanResult with all match details and actions
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.scan, text)

    def protect(
        self,
        action: Union[str, Action] = Action.FLAG,
        severity: Optional[str] = None,
        param_name: str = "prompt",
        on_block: Optional[Callable] = None,
        raise_on_block: bool = True,
        skip_llm: bool = False,
    ):
        """
        Decorator to protect a function with Nova scanning.

        Args:
            action: Action to take on match (can override policy)
            severity: Minimum severity to trigger action
            param_name: Name of the parameter to scan
            on_block: Custom handler when blocked
            raise_on_block: Whether to raise NovaBlockedError
            skip_llm: Skip LLM evaluations for faster scanning (default False)

        Returns:
            Decorator function

        Example:
            @nova.protect(action="block", severity="critical")
            def chat(prompt):
                return openai.chat(prompt)

            # Fast mode - skip LLM patterns
            @nova.protect(action="block", skip_llm=True)
            def fast_chat(prompt):
                return openai.chat(prompt)
        """
        if isinstance(action, str):
            action = Action(action)

        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                # Extract text to scan
                text = kwargs.get(param_name)
                if text is None and args:
                    text = args[0]

                if text is None:
                    return func(*args, **kwargs)

                # Scan the text
                result = self.scan(text, skip_llm=skip_llm)

                # Check if we should block
                should_block = self._should_block(result, action, severity)

                if should_block:
                    if on_block:
                        return on_block(result)
                    if raise_on_block:
                        raise NovaBlockedError(result)
                    return None

                # Use sanitized text if redaction occurred
                if result.redacted:
                    if param_name in kwargs:
                        kwargs[param_name] = result.sanitized_text
                    elif args:
                        args = (result.sanitized_text,) + args[1:]

                return func(*args, **kwargs)

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                # Extract text to scan
                text = kwargs.get(param_name)
                if text is None and args:
                    text = args[0]

                if text is None:
                    return await func(*args, **kwargs)

                # Scan the text (run sync scan in executor with skip_llm)
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, lambda: self.scan(text, skip_llm=skip_llm))

                # Check if we should block
                should_block = self._should_block(result, action, severity)

                if should_block:
                    if on_block:
                        return on_block(result)
                    if raise_on_block:
                        raise NovaBlockedError(result)
                    return None

                # Use sanitized text
                if result.redacted:
                    if param_name in kwargs:
                        kwargs[param_name] = result.sanitized_text
                    elif args:
                        args = (result.sanitized_text,) + args[1:]

                return await func(*args, **kwargs)

            # Return appropriate wrapper based on function type
            if asyncio.iscoroutinefunction(func):
                return async_wrapper
            return sync_wrapper

        return decorator

    def _should_block(self, result: ScanResult, action: Action, severity: Optional[str]) -> bool:
        """Determine if a scan result should trigger a block."""
        if action == Action.BLOCK:
            if severity:
                return (
                    result.highest_severity is not None and
                    self._severity_gte(result.highest_severity, severity)
                )
            else:
                return len(result.matches) > 0
        return result.blocked

    def _severity_gte(self, sev1: str, sev2: str) -> bool:
        """Check if severity1 >= severity2."""
        order = {"low": 1, "medium": 2, "high": 3, "critical": 4}
        return order.get(sev1.lower(), 0) >= order.get(sev2.lower(), 0)

    def _print_init_debug(self, init_time_ms: float) -> None:
        """Print initialization debug info."""
        # Count rule types
        keyword_only = sum(1 for r in self._rules if r.keywords and not r.semantics and not r.llms)
        has_semantic = sum(1 for r in self._rules if r.semantics)
        has_llm = sum(1 for r in self._rules if r.llms)

        print("\n[NOVA DEBUG] Initialization complete")
        print(f"[NOVA DEBUG] Rules loaded: {len(self._rules)} ({keyword_only} keyword-only, {has_semantic} semantic, {has_llm} LLM)")

        # Semantic model info
        if self._semantic_evaluator and self._semantic_evaluator.model:
            print(f"[NOVA DEBUG] Semantic model: {self._semantic_evaluator.model_name}")

        # LLM provider info
        if self._llm_evaluator:
            provider = self._llm_provider or "openai (default)"
            model_info = ""
            if self._llm_model:
                model_info = f" model={self._llm_model}"
            elif hasattr(self._llm_evaluator, 'model'):
                model_info = f" model={self._llm_evaluator.model}"
            print(f"[NOVA DEBUG] LLM provider: {provider}{model_info}")

        # Policy info
        policy_rules = self._policy.rules if hasattr(self._policy, 'rules') else {}
        policy_count = len(policy_rules)
        if policy_count > 0:
            items = list(policy_rules.items())[:5]
            policy_summary = ", ".join(f"{pattern}={rule.action.value.upper()}" for pattern, rule in items)
            if policy_count > 5:
                policy_summary += f", ... (+{policy_count - 5} more)"
            print(f"[NOVA DEBUG] Policy rules: {policy_count} configured ({policy_summary})")

        print(f"[NOVA DEBUG] Init time: {init_time_ms:.2f}ms")

    def _print_debug(self, text: str, result: ScanResult, scan_time_ms: float,
                      fast_rules: int = 0, llm_rules: int = 0, skipped_llm: int = 0,
                      skip_reason: str = "") -> None:
        """Print detailed debug info about scan results."""
        truncated = text[:100] + "..." if len(text) > 100 else text
        print(f"\n[NOVA DEBUG] Input: {repr(truncated)}")
        print(f"[NOVA DEBUG] Rules checked: {self.rule_count} ({fast_rules} fast, {llm_rules} LLM)")
        if skipped_llm > 0:
            reason = skip_reason or "early BLOCK"
            print(f"[NOVA DEBUG] LLM calls skipped: {skipped_llm} ({reason})")
        print(f"[NOVA DEBUG] Matches found: {result.match_count}")
        print(f"[NOVA DEBUG] Scan time: {scan_time_ms:.2f}ms")

        if not result.matches:
            print("[NOVA DEBUG] No matches - input is clean")
            return

        for i, match in enumerate(result.matches, 1):
            print(f"\nMatch {i}: {match.rule_name}")
            if match.source_file:
                print(f"  Source: {match.source_file}")
            print(f"  Action: {match.action.value.upper()}")
            print(f"  Severity: {match.severity or 'N/A'}")
            print(f"  Category: {match.meta.get('category', 'N/A')}")

            # Keywords
            if match.matching_keywords:
                matched_kw = [k for k, v in match.matching_keywords.items() if v]
                print(f"  Keywords matched: {matched_kw if matched_kw else 'None'}")
            else:
                print("  Keywords matched: None")

            # Get the rule object for pattern content lookup
            rule = self._matchers.get(match.rule_name)
            rule_obj = rule.rule if rule else None

            # Semantics with scores and pattern content
            if match.matching_semantics or match.semantic_scores:
                print("  Semantics matched:")
                for name in set(list(match.matching_semantics.keys()) + list(match.semantic_scores.keys())):
                    matched = match.matching_semantics.get(name, False)
                    score = match.semantic_scores.get(name, 0)
                    status = "← MATCH" if matched else ""
                    # Get pattern content from rule
                    pattern_text = ""
                    if rule_obj and rule_obj.semantics and name in rule_obj.semantics:
                        pattern = rule_obj.semantics[name]
                        threshold = getattr(pattern, 'threshold', 0)
                        pattern_text = f'"{pattern.pattern}" (threshold={threshold})'
                    print(f"    - {name}: {pattern_text} score={score:.3f} {status}")
            else:
                print("  Semantics matched: None")

            # LLM with scores and prompt content
            if match.matching_llm or match.llm_scores:
                print("  LLM matched:")
                for name in set(list(match.matching_llm.keys()) + list(match.llm_scores.keys())):
                    matched = match.matching_llm.get(name, False)
                    score = match.llm_scores.get(name, 0)
                    status = "← MATCH" if matched else ""
                    # Get prompt content from rule
                    prompt_text = ""
                    if rule_obj and rule_obj.llms and name in rule_obj.llms:
                        llm_pattern = rule_obj.llms[name]
                        threshold = getattr(llm_pattern, 'threshold', 0)
                        prompt_preview = llm_pattern.pattern[:50] + "..." if len(llm_pattern.pattern) > 50 else llm_pattern.pattern
                        prompt_text = f'"{prompt_preview}" (threshold={threshold})'
                    print(f"    - {name}: {prompt_text} score={score:.3f} {status}")
            else:
                print("  LLM matched: None")

        print()  # Final newline for readability

    # Convenience methods

    def add_rule(self, rule: NovaRule) -> None:
        """Add a rule to the scanner."""
        if rule.name in self._matchers:
            raise ValueError(f"Rule with name '{rule.name}' already exists")

        if self._rule_needs_llm(rule) and self._llm_evaluator is None:
            self._llm_evaluator = self._create_configured_llm_evaluator()

        self._rules.append(rule)
        self._matchers[rule.name] = NovaMatcher(
            rule=rule,
            semantic_evaluator=self._semantic_evaluator,  # Share the semantic evaluator
            llm_evaluator=self._llm_evaluator,
            create_llm_evaluator=False
        )

    def add_policy_rule(self, pattern: str, config: Dict) -> None:
        """Add a policy rule."""
        self._policy.add_rule(pattern, config)

    def set_callback(
        self,
        on_block: Optional[Callable[["ScanResult"], Any]] = None,
        on_flag: Optional[Callable[["ScanResult"], Any]] = None
    ) -> None:
        """Set global callbacks."""
        if on_block is not None:
            self._on_block = on_block
        if on_flag is not None:
            self._on_flag = on_flag

    @property
    def rules(self) -> List[NovaRule]:
        """Get all loaded rules."""
        return self._rules.copy()

    @property
    def rule_names(self) -> List[str]:
        """Get names of all loaded rules."""
        return [r.name for r in self._rules]

    @property
    def policy(self) -> NovaPolicy:
        """Get the current policy."""
        return self._policy

    @property
    def rule_count(self) -> int:
        """Get the number of loaded rules."""
        return len(self._rules)
