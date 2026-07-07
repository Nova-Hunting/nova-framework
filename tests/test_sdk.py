"""
Tests for Nova SDK

Tests covering the Nova scanning engine, decorator, async support, and debug mode.
"""

import pytest

from nova.sdk import (
    Nova,
    ScanResult,
    NovaPolicy,
    Action,
    NovaBlockedError,
    NovaConfigError,
)
from nova.core.matcher import NovaMatcher
from nova.core.rules import NovaRule, KeywordPattern, LLMPattern
from nova.evaluators.llm import OpenRouterEvaluator




# =============================================================================
# Nova Class Tests
# =============================================================================

class TestNova:
    """Tests for main Nova class."""

    def test_init_empty(self):
        """Test initializing Nova without rules."""
        nova = Nova()
        assert nova.rule_count == 0

    def test_init_with_policy_dict(self):
        """Test initializing with policy dict."""
        nova = Nova(policy={"PI": {"action": "block"}})
        assert nova.policy is not None

    def test_init_with_policy_object(self):
        """Test initializing with NovaPolicy object."""
        policy = NovaPolicy({"PI": {"action": "block"}})
        nova = Nova(policy=policy)
        assert nova.policy == policy

    def test_init_with_duplicate_rules_raises_config_error(self):
        """Test duplicate constructor rules fail closed."""
        rule = NovaRule(name="DuplicateRule", condition="true")

        with pytest.raises(NovaConfigError, match="Duplicate rule name"):
            Nova(rules=[rule, rule])

    def test_add_rule(self):
        """Test adding rule dynamically."""
        nova = Nova()
        rule = NovaRule(
            name="TestRule",
            keywords={"$test": KeywordPattern(pattern="test")},
            condition="$test"
        )
        nova.add_rule(rule)
        assert nova.rule_count == 1
        assert "TestRule" in nova.rule_names

    def test_add_duplicate_rule_raises(self):
        """Test that adding duplicate rule raises error."""
        nova = Nova()
        rule = NovaRule(name="TestRule", condition="true")
        nova.add_rule(rule)
        with pytest.raises(ValueError):
            nova.add_rule(rule)

    def test_add_llm_rule_uses_configured_provider(self, monkeypatch):
        """Test dynamic LLM rules use the SDK-configured provider."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
        nova = Nova(llm_provider="openrouter", llm_model="google/gemini-2.5-pro")
        rule = NovaRule(
            name="DynamicLLMRule",
            llms={"$judge": LLMPattern("Detect unsafe content")},
            condition="llm.$judge",
        )

        nova.add_rule(rule)

        matcher = nova._matchers["DynamicLLMRule"]
        assert isinstance(matcher.llm_evaluator, OpenRouterEvaluator)
        assert matcher.llm_evaluator.model == "google/gemini-2.5-pro"

    def test_add_llm_rule_with_configured_provider_requires_key(self, monkeypatch):
        """Test dynamic provider initialization fails closed when required key is missing."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        nova = Nova(llm_provider="openrouter")
        rule = NovaRule(
            name="DynamicLLMRule",
            llms={"$judge": LLMPattern("Detect unsafe content")},
            condition="llm.$judge",
        )

        with pytest.raises(NovaConfigError, match="OPENROUTER_API_KEY"):
            nova.add_rule(rule)

        assert "DynamicLLMRule" not in nova.rule_names

    def test_missing_rules_path_raises_config_error(self, tmp_path):
        """Test missing rules_path fails closed."""
        with pytest.raises(NovaConfigError, match="Rules path does not exist"):
            Nova(rules_path=tmp_path / "missing")

    def test_invalid_rule_file_raises_config_error(self, tmp_path):
        """Test malformed rule files fail closed by default."""
        rule_file = tmp_path / "broken.nov"
        rule_file.write_text("rule BrokenRule { keywords: $bad = [", encoding="utf-8")

        with pytest.raises(NovaConfigError, match="Failed to load rule file"):
            Nova(rules_path=rule_file)

    def test_ignore_invalid_rules_preserves_skip_behavior(self, tmp_path):
        """Test invalid rules can still be skipped when explicitly requested."""
        rule_file = tmp_path / "broken.nov"
        rule_file.write_text("rule BrokenRule { keywords: $bad = [", encoding="utf-8")

        nova = Nova(rules_path=rule_file, ignore_invalid_rules=True)

        assert nova.rule_count == 0

    def test_rules_path_loads_nested_rule_files(self, tmp_path):
        """Test directory loading finds nested .nov rule files."""
        nested = tmp_path / "nested"
        nested.mkdir()
        rule_file = nested / "keyword.nov"
        rule_file.write_text(
            """
rule NestedKeywordRule
{
    keywords:
        $safe = "safe"

    condition:
        keywords.$safe
}
""",
            encoding="utf-8",
        )

        nova = Nova(rules_path=tmp_path)

        assert nova.rule_names == ["NestedKeywordRule"]

    def test_rules_path_duplicate_rule_names_raise_config_error(self, tmp_path):
        """Test duplicate rule names across files fail closed."""
        first = tmp_path / "first.nov"
        second = tmp_path / "second.nov"
        rule_text = """
rule DuplicateFromFile
{
    keywords:
        $safe = "safe"

    condition:
        keywords.$safe
}
"""
        first.write_text(rule_text, encoding="utf-8")
        second.write_text(rule_text, encoding="utf-8")

        with pytest.raises(NovaConfigError, match="Duplicate rule name"):
            Nova(rules_path=tmp_path)

    def test_rules_path_ignores_rule_words_inside_metadata_values(self, tmp_path):
        """Test single-rule file detection ignores metadata text containing 'rule'."""
        rule_file = tmp_path / "metadata_rule_word.nov"
        rule_file.write_text(
            """
rule MetadataRuleWord
{
    meta:
        description = "This rule explains the word rule in prose"

    keywords:
        $safe = "safe"

    condition:
        keywords.$safe
}
""",
            encoding="utf-8",
        )

        nova = Nova(rules_path=rule_file)

        assert nova.rule_names == ["MetadataRuleWord"]

    def test_scan_no_match(self):
        """Test scanning with no matches."""
        nova = Nova()
        rule = NovaRule(
            name="TestRule",
            keywords={"$test": KeywordPattern(pattern="blocked")},
            condition="$test"
        )
        nova.add_rule(rule)
        result = nova.scan("hello world")
        assert result.clean is True
        assert result.blocked is False

    def test_scan_with_match(self):
        """Test scanning with a match."""
        nova = Nova(policy={"Test": {"action": "flag"}})
        rule = NovaRule(
            name="TestRule",
            keywords={"$test": KeywordPattern(pattern="hello")},
            condition="$test"
        )
        nova.add_rule(rule)
        result = nova.scan("hello world")
        assert result.clean is False
        assert len(result.matches) == 1
        assert result.matches[0].matched_patterns == ["$test"]

    def test_scan_with_block_policy(self):
        """Test scanning with BLOCK policy."""
        nova = Nova(policy={"Test": {"action": "block"}})
        rule = NovaRule(
            name="TestRule",
            keywords={"$test": KeywordPattern(pattern="blocked")},
            condition="$test"
        )
        nova.add_rule(rule)
        result = nova.scan("this is blocked content")
        assert result.blocked is True

    def test_scan_normalizes_unicode_for_matching(self):
        """Test SDK scanning applies the same Unicode normalization as core scanner."""
        nova = Nova(policy={"UnicodeBypassRule": {"action": "block"}})
        rule = NovaRule(
            name="UnicodeBypassRule",
            keywords={"$inject": KeywordPattern(pattern="ignore previous")},
            condition="keywords.$inject",
        )
        nova.add_rule(rule)

        result = nova.scan("\u0456gnore previous instructions")

        assert result.blocked is True
        assert result.original_text == "\u0456gnore previous instructions"

    def test_redaction_falls_back_to_normalized_text_for_unicode_matches(self):
        """Test redaction does not miss keyword matches caused by normalized text."""
        nova = Nova(policy={"UnicodeRedactRule": {"action": "redact"}})
        rule = NovaRule(
            name="UnicodeRedactRule",
            keywords={"$secret": KeywordPattern(pattern="api key")},
            condition="keywords.$secret",
        )
        nova.add_rule(rule)

        result = nova.scan("leaked api\u200b key in prompt")

        assert result.redacted is True
        assert result.original_text == "leaked api\u200b key in prompt"
        assert result.sanitized_text == "leaked [REDACTED] in prompt"
        assert result.redactions[0]["normalized"] is True

    def test_matcher_skip_llm_does_not_call_evaluator(self):
        """Test fast-only matching skips LLM calls without removing the evaluator."""
        class FakeLLMEvaluator:
            def __init__(self):
                self.calls = []

            def evaluate_prompt(self, prompt_template, text, temperature=0.1):
                self.calls.append((prompt_template, text, temperature))
                return True, 0.9, {"reason": "matched"}

        evaluator = FakeLLMEvaluator()
        rule = NovaRule(
            name="LLMRule",
            llms={"$judge": LLMPattern("Detect unsafe content")},
            condition="llm.$judge",
        )
        matcher = NovaMatcher(rule=rule, llm_evaluator=evaluator)

        fast_result = matcher.check_prompt("unsafe text", skip_llm=True)
        full_result = matcher.check_prompt("unsafe text")

        assert fast_result["matched"] is False
        assert full_result["matched"] is True
        assert evaluator.calls == [("Detect unsafe content", "unsafe text", 0.1)]
        assert matcher.llm_evaluator is evaluator

    def test_matcher_skip_llm_fails_closed_for_negated_llm_condition(self):
        """Test skipped LLM values cannot satisfy negated LLM conditions."""
        class FakeLLMEvaluator:
            def __init__(self):
                self.calls = []

            def evaluate_prompt(self, prompt_template, text, temperature=0.1):
                self.calls.append((prompt_template, text, temperature))
                return True, 0.9, {"reason": "safe"}

        evaluator = FakeLLMEvaluator()
        rule = NovaRule(
            name="NegatedLLMRule",
            llms={"$safe": LLMPattern("Detect safe content")},
            condition="not llm.$safe",
        )
        matcher = NovaMatcher(rule=rule, llm_evaluator=evaluator)

        fast_result = matcher.check_prompt("unsafe text", skip_llm=True)
        full_result = matcher.check_prompt("unsafe text")

        assert fast_result["matched"] is False
        assert "skipped LLM evaluation" in fast_result["debug"]["evaluation_warnings"][0]
        assert full_result["matched"] is False
        assert evaluator.calls == [("Detect safe content", "unsafe text", 0.1)]

    def test_sdk_fast_phase_uses_non_mutating_skip_llm(self, monkeypatch):
        """Test SDK fast phase does not disable shared matcher LLM state."""
        class FakeLLMEvaluator:
            def evaluate_prompt(self, prompt_template, text, temperature=0.1):
                return True, 0.9, {"reason": "matched"}

        original_check_prompt = NovaMatcher.check_prompt
        skip_llm_calls = []

        def check_prompt_spy(self, prompt, *args, **kwargs):
            skip_llm_calls.append(kwargs.get("skip_llm", False))
            return original_check_prompt(self, prompt, *args, **kwargs)

        rule = NovaRule(
            name="SDKLLMRule",
            llms={"$judge": LLMPattern("Detect unsafe content")},
            condition="llm.$judge",
        )
        nova = Nova(rules=[rule], policy={"SDKLLMRule": {"action": "flag"}})
        evaluator = FakeLLMEvaluator()
        nova._llm_evaluator = evaluator
        nova._matchers["SDKLLMRule"].llm_evaluator = evaluator
        monkeypatch.setattr(NovaMatcher, "check_prompt", check_prompt_spy)

        result = nova.scan("unsafe text")

        assert result.match_count == 1
        assert True in skip_llm_calls
        assert nova._matchers["SDKLLMRule"].llm_evaluator is evaluator

    def test_scan_result_surfaces_fail_closed_llm_warnings(self):
        """Test SDK callers can see fail-closed LLM errors even when no rule matches."""
        class ErrorLLMEvaluator:
            def evaluate_prompt(self, prompt_template, text, temperature=0.1):
                return False, 0.0, {"error": "provider unavailable"}

        rule = NovaRule(
            name="SDKFailClosedLLMRule",
            llms={"$safe": LLMPattern("Detect safe content")},
            condition="not llm.$safe",
        )
        nova = Nova(rules=[rule])
        evaluator = ErrorLLMEvaluator()
        nova._llm_evaluator = evaluator
        nova._matchers["SDKFailClosedLLMRule"].llm_evaluator = evaluator

        result = nova.scan("unsafe text")

        assert result.clean is True
        assert result.has_warnings is True
        assert "llm.$safe evaluation errored" in result.warnings[0]
        assert result.rule_warnings["SDKFailClosedLLMRule"] == result.warnings

    def test_scan_result_surfaces_skip_llm_warnings(self):
        """Test explicit skip_llm warnings are visible to high-level SDK callers."""
        class MatchingLLMEvaluator:
            def evaluate_prompt(self, prompt_template, text, temperature=0.1):
                return True, 0.9, {"reason": "safe"}

        rule = NovaRule(
            name="SDKSkipLLMRule",
            llms={"$safe": LLMPattern("Detect safe content")},
            condition="not llm.$safe",
        )
        nova = Nova(rules=[rule])
        evaluator = MatchingLLMEvaluator()
        nova._llm_evaluator = evaluator
        nova._matchers["SDKSkipLLMRule"].llm_evaluator = evaluator

        result = nova.scan("unsafe text", skip_llm=True)

        assert result.clean is True
        assert result.has_warnings is True
        assert "skipped LLM evaluation" in result.warnings[0]
        assert result.to_dict()["warnings"] == result.warnings

    def test_parallel_llm_worker_exceptions_surface_as_warnings(self, monkeypatch):
        """Test SDK parallel LLM worker failures are not silently swallowed."""
        original_check_prompt = NovaMatcher.check_prompt

        def raising_full_llm_check(self, prompt, *args, **kwargs):
            if kwargs.get("skip_llm", False):
                return original_check_prompt(self, prompt, *args, **kwargs)
            raise RuntimeError("worker crashed")

        rules = [
            NovaRule(
                name="SDKParallelFailureOne",
                llms={"$judge": LLMPattern("Detect unsafe content")},
                condition="llm.$judge",
            ),
            NovaRule(
                name="SDKParallelFailureTwo",
                llms={"$judge": LLMPattern("Detect unsafe content")},
                condition="llm.$judge",
            ),
        ]
        nova = Nova(rules=rules)
        monkeypatch.setattr(NovaMatcher, "check_prompt", raising_full_llm_check)

        result = nova.scan("unsafe text", parallel=True)

        assert result.clean is True
        assert result.has_warnings is True
        assert len(result.warnings) == 2
        assert all("SDK LLM evaluation errored" in warning for warning in result.warnings)
        assert set(result.rule_warnings) == {"SDKParallelFailureOne", "SDKParallelFailureTwo"}


class TestNovaDecorator:
    """Tests for Nova protect decorator."""

    def test_decorator_allows_clean_input(self):
        """Test decorator allows clean input through."""
        nova = Nova()
        rule = NovaRule(
            name="TestRule",
            keywords={"$test": KeywordPattern(pattern="blocked")},
            condition="$test"
        )
        nova.add_rule(rule)

        @nova.protect(action="block")
        def process(prompt):
            return f"processed: {prompt}"

        result = process("hello world")
        assert result == "processed: hello world"

    def test_decorator_blocks_malicious_input(self):
        """Test decorator blocks malicious input."""
        nova = Nova(policy={"Test": {"action": "block"}})
        rule = NovaRule(
            name="TestRule",
            keywords={"$test": KeywordPattern(pattern="malicious")},
            condition="$test"
        )
        nova.add_rule(rule)

        @nova.protect(action="block", raise_on_block=True)
        def process(prompt):
            return f"processed: {prompt}"

        with pytest.raises(NovaBlockedError):
            process("this is malicious input")

    def test_decorator_with_custom_handler(self):
        """Test decorator with custom block handler."""
        nova = Nova(policy={"Test": {"action": "block"}})
        rule = NovaRule(
            name="TestRule",
            keywords={"$test": KeywordPattern(pattern="blocked")},
            condition="$test"
        )
        nova.add_rule(rule)

        @nova.protect(action="block", on_block=lambda r: "BLOCKED", raise_on_block=False)
        def process(prompt):
            return f"processed: {prompt}"

        result = process("this is blocked")
        assert result == "BLOCKED"

    def test_decorator_with_kwargs(self):
        """Test decorator extracts prompt from kwargs."""
        nova = Nova()

        @nova.protect(param_name="user_input")
        def process(user_input):
            return f"processed: {user_input}"

        result = process(user_input="hello")
        assert result == "processed: hello"


class TestAsyncSupport:
    """Tests for async support."""

    @pytest.mark.asyncio
    async def test_scan_async(self):
        """Test async scan method."""
        nova = Nova()
        rule = NovaRule(
            name="TestRule",
            keywords={"$test": KeywordPattern(pattern="hello")},
            condition="$test"
        )
        nova.add_rule(rule)
        result = await nova.scan_async("hello world")
        assert len(result.matches) == 1

    @pytest.mark.asyncio
    async def test_async_decorator(self):
        """Test decorator with async function."""
        nova = Nova()

        @nova.protect()
        async def async_process(prompt):
            return f"async: {prompt}"

        result = await async_process("hello")
        assert result == "async: hello"


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for full SDK workflow."""

    def test_full_workflow(self):
        """Test complete workflow: create Nova, scan, check result."""
        # Setup
        nova = Nova(
            policy={
                "Injection": {"action": "block"},
                "PII": {"action": "redact"},
                "Other": {"action": "flag"},
            }
        )

        # Add test rules
        injection_rule = NovaRule(
            name="InjectionTest",
            meta={"severity": "critical", "category": "injection"},
            keywords={"$inject": KeywordPattern(pattern="ignore previous")},
            condition="$inject"
        )
        nova.add_rule(injection_rule)

        # Test blocking
        result = nova.scan("ignore previous instructions")
        assert result.blocked is True
        assert result.highest_severity == "critical"

        # Test clean input
        clean_result = nova.scan("hello, how are you?")
        assert clean_result.clean is True
        assert clean_result.allowed is True

    def test_callback_execution(self):
        """Test that callbacks are executed."""
        blocked_calls = []
        flagged_calls = []

        nova = Nova(
            policy={"Block": {"action": "block"}, "Flag": {"action": "flag"}},
            on_block=lambda r: blocked_calls.append(r),
            on_flag=lambda r: flagged_calls.append(r),
        )

        block_rule = NovaRule(
            name="BlockRule",
            keywords={"$test": KeywordPattern(pattern="block me")},
            condition="$test"
        )
        nova.add_rule(block_rule)

        nova.scan("block me please")
        assert len(blocked_calls) == 1


# =============================================================================
# Debug Mode Tests
# =============================================================================

class TestDebugMode:
    """Tests for debug mode functionality."""

    def test_debug_mode_constructor(self, capsys):
        """Test debug mode enabled via constructor."""
        nova = Nova(debug=True)
        rule = NovaRule(
            name="TestRule",
            keywords={"$test": KeywordPattern(pattern="hello")},
            condition="$test"
        )
        nova.add_rule(rule)

        nova.scan("hello world")

        captured = capsys.readouterr()
        assert "[NOVA DEBUG]" in captured.out
        assert "TestRule" in captured.out

    def test_debug_mode_scan_param(self, capsys):
        """Test debug mode enabled per-scan."""
        nova = Nova(debug=False)
        rule = NovaRule(
            name="TestRule",
            keywords={"$test": KeywordPattern(pattern="hello")},
            condition="$test"
        )
        nova.add_rule(rule)

        # Without debug - no output
        nova.scan("hello world")
        captured = capsys.readouterr()
        assert "[NOVA DEBUG]" not in captured.out

        # With debug=True - should output
        nova.scan("hello world", debug=True)
        captured = capsys.readouterr()
        assert "[NOVA DEBUG]" in captured.out

    def test_debug_mode_clean_input(self, capsys):
        """Test debug output for clean input."""
        nova = Nova(debug=True)
        rule = NovaRule(
            name="TestRule",
            keywords={"$test": KeywordPattern(pattern="blocked")},
            condition="$test"
        )
        nova.add_rule(rule)

        nova.scan("hello world")

        captured = capsys.readouterr()
        assert "No matches - input is clean" in captured.out

    def test_scan_result_print_debug(self, capsys):
        """Test ScanResult.print_debug() method."""
        from nova.sdk import RuleMatch

        match = RuleMatch(
            rule_name="TestRule",
            meta={"category": "test", "severity": "high"},
            action=Action.BLOCK,
            severity="high",
            matching_keywords={"$keyword": True},
            matching_semantics={},
            semantic_scores={},
        )
        result = ScanResult(
            original_text="test input",
            sanitized_text="test input",
            matches=[match]
        )

        result.print_debug()

        captured = capsys.readouterr()
        assert "[NOVA DEBUG] Scan Result Summary" in captured.out
        assert "TestRule" in captured.out
        assert "BLOCK" in captured.out

    def test_debug_shows_semantic_scores(self, capsys):
        """Test that debug output shows semantic scores."""
        from nova.sdk import RuleMatch

        match = RuleMatch(
            rule_name="SemanticRule",
            meta={},
            action=Action.FLAG,
            severity=None,
            matching_keywords={},
            matching_semantics={"$semantic": True},
            semantic_scores={"$semantic": 0.85},
        )
        result = ScanResult(
            original_text="test",
            sanitized_text="test",
            matches=[match]
        )

        result.print_debug()

        captured = capsys.readouterr()
        assert "$semantic" in captured.out
        assert "0.850" in captured.out
        assert "← MATCH" in captured.out
