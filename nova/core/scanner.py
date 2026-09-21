"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia
twitter: @fr0gger_
License: MIT License
Version: see nova._version
Description: Scanner for checking prompts against multiple Nova rules
"""

import threading
from typing import List, Dict, Any, Optional

from nova.core.matcher import NovaMatcher
from nova.core.rules import NovaRule
from nova.evaluators.llm import OpenAIEvaluator, LLMEvaluator, get_validated_evaluator
from nova.utils.logger import get_logger
from nova.utils.helpers import normalize_unicode

# Get logger for this module
logger = get_logger("nova.scanner")

class NovaScanner:
    """
    Scanner that checks prompts against multiple Nova rules.
    """
    
    def __init__(
        self,
        rules: List[NovaRule] = None,
        llm_type: Optional[str] = None,
        llm_model: Optional[str] = None,
        llm_evaluator: Optional[LLMEvaluator] = None,
        *, sys1_config=None, sys1_evaluator=None,
    ):
        """
        Initialize the scanner with a list of rules.

        Args:
            rules: List of NovaRule objects to check against (optional)
            llm_type: Optional LLM provider for rules that require LLM evaluation.
                      Supported values match novarun: openai, anthropic, azure,
                      ollama, groq, and openrouter.
            llm_model: Optional model/deployment override for the selected provider.
            llm_evaluator: Optional pre-built evaluator to reuse for all LLM rules.
        """
        self._sys1_options = sys1_config
        self._sys1_evaluator = sys1_evaluator
        self.rules = rules or []
        self._matchers = {}
        self._llm_type = llm_type
        self._llm_model = llm_model
        self._provided_llm_evaluator = llm_evaluator
        self._llm_evaluator = llm_evaluator
        self._evaluator_lock = threading.Lock()  # Thread-safe evaluator initialization
        self._validate_unique_rule_names(self.rules)

        # Check if any rules need LLM evaluation and create a single shared evaluator if needed
        if self.rules:
            self._initialize_evaluators()

        # Initialize matchers for provided rules
        for rule in self.rules:
            self._create_matcher(rule)

    def _create_llm_evaluator(self) -> LLMEvaluator:
        """Create the configured shared LLM evaluator."""
        if self._provided_llm_evaluator:
            return self._provided_llm_evaluator
        if self._llm_type:
            return get_validated_evaluator(self._llm_type, self._llm_model)
        return OpenAIEvaluator(model=self._llm_model or "gpt-4o-mini")

    def _validate_unique_rule_names(self, rules: List[NovaRule]) -> None:
        """Validate that rule names are unique within the provided collection."""
        seen_names = set()
        duplicate_names = set()
        for rule in rules:
            if rule.name in seen_names:
                duplicate_names.add(rule.name)
            seen_names.add(rule.name)

        if duplicate_names:
            sorted_names = ", ".join(sorted(duplicate_names))
            raise ValueError(f"Duplicate rule name(s): {sorted_names}")

    def _initialize_evaluators(self):
        """Initialize evaluators based on rule needs (thread-safe)."""
        # Check if any rule needs LLM evaluation
        needs_llm = any(self._rule_needs_llm(rule) for rule in self.rules)

        # Create LLM evaluator only if needed, with thread safety
        if needs_llm and self._llm_evaluator is None:
            with self._evaluator_lock:
                # Double-check after acquiring lock
                if self._llm_evaluator is None:
                    logger.info("Creating single shared LLM evaluator for all rules...")
                    self._llm_evaluator = self._create_llm_evaluator()
    
    def _rule_needs_llm(self, rule: NovaRule) -> bool:
        """Check if a rule requires LLM evaluation."""
        if rule.llms:
            return True
        if rule.condition and 'llm.' in rule.condition.lower():
            return True
        return False
    
    def _create_matcher(self, rule: NovaRule) -> NovaMatcher:
        """Create a matcher for a rule, with shared evaluators."""
        if rule.sys1 and self._sys1_evaluator is None:
            from nova.evaluators.sys1.factory import create_sys1_evaluator
            self._sys1_evaluator = create_sys1_evaluator(self._sys1_options)
        # Create matcher with shared LLM evaluator if one exists
        matcher = NovaMatcher(
            rule=rule,
            llm_evaluator=self._llm_evaluator,
            # Don't create a new LLM evaluator if we didn't create one already
            create_llm_evaluator=self._llm_evaluator is None,
            sys1_config=self._sys1_options, sys1_evaluator=self._sys1_evaluator
        )
        self._matchers[rule.name] = matcher
        return matcher
    
    def add_rule(self, rule: NovaRule) -> None:
        """
        Add a single rule to the scanner.
        
        Args:
            rule: NovaRule object to add
            
        Raises:
            ValueError: If a rule with the same name already exists
        """
        if rule.name in self._matchers:
            raise ValueError(f"Rule with name '{rule.name}' already exists")
            
        # Check if we need to create LLM evaluator (thread-safe)
        if self._llm_evaluator is None and self._rule_needs_llm(rule):
            with self._evaluator_lock:
                # Double-check after acquiring lock
                if self._llm_evaluator is None:
                    logger.info("Creating LLM evaluator for newly added rule that requires it...")
                    self._llm_evaluator = self._create_llm_evaluator()
        
        self.rules.append(rule)
        self._create_matcher(rule)
    
    def add_rules(self, rules: List[NovaRule]) -> None:
        """
        Add multiple rules to the scanner.
        
        Args:
            rules: List of NovaRule objects to add
            
        Raises:
            ValueError: If any rule has a duplicate name
        """
        seen_names = set()
        duplicate_names = set()
        for rule in rules:
            if rule.name in self._matchers or rule.name in seen_names:
                duplicate_names.add(rule.name)
            seen_names.add(rule.name)

        if duplicate_names:
            sorted_names = ", ".join(sorted(duplicate_names))
            raise ValueError(f"Duplicate rule name(s): {sorted_names}")

        # Check if any of the new rules need LLM (thread-safe)
        if self._llm_evaluator is None and any(self._rule_needs_llm(rule) for rule in rules):
            with self._evaluator_lock:
                # Double-check after acquiring lock
                if self._llm_evaluator is None:
                    logger.info("Creating LLM evaluator for newly added rules that require it...")
                    self._llm_evaluator = self._create_llm_evaluator()
        
        for rule in rules:
            self.rules.append(rule)
            self._create_matcher(rule)
    
    def scan(self, prompt: str, *, sys1_state=None, skip_sys1=False, skip_llm=False) -> List[Dict[str, Any]]:
        """
        Scan a prompt against all loaded rules.

        Args:
            prompt: The prompt text to scan

        Returns:
            List of match results for rules that matched
        """
        if any(rule.sys1 for rule in self.rules):
            details = self.scan_with_details(prompt, sys1_state=sys1_state, skip_sys1=skip_sys1, skip_llm=skip_llm)
            return [result for result in details["detailed_results"].values() if result["matched"]]
        # Normalize Unicode to prevent homoglyph evasion attacks
        prompt = normalize_unicode(prompt)

        results = []

        for rule in self.rules:
            matcher = self._matchers[rule.name]
            result = matcher.check_prompt(prompt, skip_llm=skip_llm)
            
            if result['matched']:
                results.append(result)
        
        return results
    
    def scan_with_details(self, prompt: str, *, sys1_state=None, skip_sys1=False, skip_llm=False) -> Dict[str, Any]:
        """
        Scan a prompt and return detailed results for all rules.

        Args:
            prompt: The prompt text to scan

        Returns:
            Dictionary with comprehensive scan results
        """
        if any(rule.sys1 for rule in self.rules):
            from nova.evaluators.sys1.engine import collect
            from nova.core.sys1 import NovaEvaluationError
            results, causes = collect(self.rules, self._matchers, prompt, normalize_unicode(prompt),
                                     context=sys1_state, skip_llm=skip_llm, skip_sys1=skip_sys1)
            matches = [{"rule_name": rule.name, "meta": rule.meta} for rule, result in results if result["matched"]]
            details = {"prompt": prompt, "matched_any": bool(matches), "matches": matches,
                       "match_count": len(matches), "scanned_rules": len(self.rules),
                       "detailed_results": {rule.name: result for rule, result in results},
                       "sys1_results": {rule.name: result["sys1_results"] for rule, result in results if rule.sys1},
                       "evaluation_complete": not causes}
            if causes:
                raise NovaEvaluationError(details, causes)
            return details
        # Normalize Unicode to prevent homoglyph evasion attacks
        prompt = normalize_unicode(prompt)

        all_matches = []
        all_results = {}
        
        for rule in self.rules:
            matcher = self._matchers[rule.name]
            result = matcher.check_prompt(prompt, skip_llm=skip_llm)
            
            # Add to matches list if matched
            if result['matched']:
                all_matches.append({
                    'rule_name': rule.name,
                    'meta': rule.meta
                })
            
            # Store full result for reference
            all_results[rule.name] = result
        
        return {
            'prompt': prompt,
            'matched_any': len(all_matches) > 0,
            'matches': all_matches,
            'match_count': len(all_matches),
            'scanned_rules': len(self.rules),
            'detailed_results': all_results
        }
    
    def get_rule_names(self) -> List[str]:
        """
        Get names of all loaded rules.
        
        Returns:
            List of rule names
        """
        return [rule.name for rule in self.rules]
    
    def clear_rules(self) -> None:
        """Clear all loaded rules."""
        self.rules = []
        self._matchers = {}
        # Also clear the LLM evaluator since we don't need it anymore
        self._llm_evaluator = None
