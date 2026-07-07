"""
Tests for Nova SDK components

Tests covering the policy system, scan results, and redaction.
"""

import pytest

from nova.sdk import (
    ScanResult,
    RuleMatch,
    NovaPolicy,
    PolicyRule,
    Action,
    Redactor,
)
from nova.core.rules import KeywordPattern


# =============================================================================
# Policy Tests
# =============================================================================

class TestAction:
    """Tests for Action enum."""

    def test_action_values(self):
        """Test that all action values are correct."""
        assert Action.ALLOW.value == "allow"
        assert Action.FLAG.value == "flag"
        assert Action.REDACT.value == "redact"
        assert Action.BLOCK.value == "block"

    def test_action_from_string(self):
        """Test creating Action from string."""
        assert Action("block") == Action.BLOCK
        assert Action("flag") == Action.FLAG


class TestPolicyRule:
    """Tests for PolicyRule dataclass."""

    def test_default_values(self):
        """Test default PolicyRule values."""
        rule = PolicyRule()
        assert rule.action == Action.FLAG
        assert rule.severity is None
        assert rule.message is None
        assert rule.callback is None

    def test_custom_values(self):
        """Test PolicyRule with custom values."""
        def callback(x):
            return x

        rule = PolicyRule(
            action=Action.BLOCK,
            severity="critical",
            message="Blocked!",
            callback=callback
        )
        assert rule.action == Action.BLOCK
        assert rule.severity == "critical"
        assert rule.message == "Blocked!"
        assert rule.callback == callback


class TestNovaPolicy:
    """Tests for NovaPolicy class."""

    def test_empty_policy(self):
        """Test empty policy uses default action."""
        policy = NovaPolicy()
        result = policy.get_action_for_match("TestRule", {})
        assert result.action == Action.FLAG

    def test_exact_match(self):
        """Test exact rule name matching."""
        policy = NovaPolicy({
            "PromptInjection": {"action": "block"}
        })
        result = policy.get_action_for_match("PromptInjection", {})
        assert result.action == Action.BLOCK

    def test_prefix_match(self):
        """Test rule name prefix matching."""
        policy = NovaPolicy({
            "PI": {"action": "block"}
        })
        result = policy.get_action_for_match("PIJailbreak", {})
        assert result.action == Action.BLOCK

    def test_category_wildcard(self):
        """Test category wildcard matching."""
        policy = NovaPolicy({
            "jailbreak/*": {"action": "flag"}
        })
        result = policy.get_action_for_match("TestRule", {"category": "jailbreak/roleplay"})
        assert result.action == Action.FLAG

    def test_severity_default(self):
        """Test severity-based default action."""
        policy = NovaPolicy()
        result = policy.get_action_for_match("TestRule", {"severity": "critical"})
        assert result.action == Action.BLOCK

        result = policy.get_action_for_match("TestRule", {"severity": "low"})
        assert result.action == Action.ALLOW

    def test_policy_priority(self):
        """Test that exact match takes priority over prefix."""
        policy = NovaPolicy({
            "PI": {"action": "flag"},
            "PITest": {"action": "block"}
        })
        result = policy.get_action_for_match("PITest", {})
        assert result.action == Action.BLOCK

    def test_add_rule(self):
        """Test adding rules dynamically."""
        policy = NovaPolicy()
        policy.add_rule("Test", {"action": "block"})
        result = policy.get_action_for_match("Test", {})
        assert result.action == Action.BLOCK

    def test_policy_normalizes_string_default_and_severity_actions(self):
        """Test string actions behave the same as Action enum values."""
        policy = NovaPolicy(
            default_action="allow",
            severity_actions={"critical": "block", "medium": "flag"},
        )

        assert policy.get_action_for_match("UnknownRule", {}).action == Action.ALLOW
        assert policy.get_action_for_match("UnknownRule", {"severity": "critical"}).action == Action.BLOCK
        assert policy.get_action_for_match("UnknownRule", {"severity": "medium"}).action == Action.FLAG

    def test_policy_normalizes_policy_rule_and_setters(self):
        """Test PolicyRule and setter actions are normalized consistently."""
        policy = NovaPolicy({"ExactRule": PolicyRule(action="BLOCK")})
        policy.set_default_action("redact")
        policy.set_severity_action("low", "allow")

        assert policy.get_action_for_match("ExactRule", {}).action == Action.BLOCK
        assert policy.get_action_for_match("UnknownRule", {"severity": "low"}).action == Action.ALLOW
        assert policy.get_action_for_match("UnknownRule", {}).action == Action.REDACT

    def test_policy_accepts_string_action_shorthand(self):
        """Test common compact policy syntax maps directly to actions."""
        policy = NovaPolicy({"PromptInjection": "block"})

        assert policy.get_action_for_match("PromptInjection", {}).action == Action.BLOCK

    def test_policy_rejects_invalid_shapes_with_clear_errors(self):
        """Test malformed policy config fails with deliberate validation errors."""
        with pytest.raises(ValueError, match="rules must be a mapping"):
            NovaPolicy(rules=["PromptInjection"])

        with pytest.raises(ValueError, match="non-empty string"):
            NovaPolicy({"": {"action": "block"}})

        with pytest.raises(ValueError, match="must be a mapping, PolicyRule, string, or Action"):
            NovaPolicy({"PromptInjection": object()})

        with pytest.raises(ValueError, match="callback.*callable"):
            NovaPolicy({"PromptInjection": {"action": "block", "callback": "not-callable"}})

        with pytest.raises(ValueError, match="severity_actions must be a mapping"):
            NovaPolicy(severity_actions=["critical"])


# =============================================================================
# ScanResult Tests
# =============================================================================

class TestScanResult:
    """Tests for ScanResult class."""

    def test_empty_result(self):
        """Test empty scan result properties."""
        result = ScanResult(
            original_text="test",
            sanitized_text="test"
        )
        assert result.clean is True
        assert result.blocked is False
        assert result.flagged is False
        assert result.redacted is False
        assert result.allowed is True
        assert result.match_count == 0

    def test_blocked_result(self):
        """Test result with BLOCK action."""
        match = RuleMatch(
            rule_name="TestRule",
            meta={"severity": "high"},
            action=Action.BLOCK,
            severity="high"
        )
        result = ScanResult(
            original_text="test",
            sanitized_text="test",
            matches=[match]
        )
        assert result.blocked is True
        assert result.allowed is False
        assert result.clean is False
        assert result.blocked_rules == ["TestRule"]

    def test_flagged_result(self):
        """Test result with FLAG action."""
        match = RuleMatch(
            rule_name="TestRule",
            meta={},
            action=Action.FLAG,
            severity=None
        )
        result = ScanResult(
            original_text="test",
            sanitized_text="test",
            matches=[match]
        )
        assert result.flagged is True
        assert result.blocked is False
        assert result.flagged_rules == ["TestRule"]

    def test_highest_severity(self):
        """Test highest severity calculation."""
        matches = [
            RuleMatch(rule_name="Low", meta={"severity": "low"}, action=Action.FLAG, severity="low"),
            RuleMatch(rule_name="Critical", meta={"severity": "critical"}, action=Action.FLAG, severity="critical"),
            RuleMatch(rule_name="Medium", meta={"severity": "medium"}, action=Action.FLAG, severity="medium"),
        ]
        result = ScanResult(
            original_text="test",
            sanitized_text="test",
            matches=matches
        )
        assert result.highest_severity == "critical"

    def test_get_matches_by_action(self):
        """Test filtering matches by action."""
        matches = [
            RuleMatch(rule_name="Block1", meta={}, action=Action.BLOCK, severity=None),
            RuleMatch(rule_name="Flag1", meta={}, action=Action.FLAG, severity=None),
            RuleMatch(rule_name="Block2", meta={}, action=Action.BLOCK, severity=None),
        ]
        result = ScanResult(
            original_text="test",
            sanitized_text="test",
            matches=matches
        )
        blocked = result.get_matches_by_action(Action.BLOCK)
        assert len(blocked) == 2
        assert all(m.action == Action.BLOCK for m in blocked)

    def test_to_dict(self):
        """Test serialization to dict."""
        result = ScanResult(
            original_text="test input",
            sanitized_text="test input",
            warnings=["LLM evaluation skipped"],
            rule_warnings={"RuleA": ["LLM evaluation skipped"]},
        )
        d = result.to_dict()
        assert d["blocked"] is False
        assert d["clean"] is True
        assert d["original_text"] == "test input"
        assert d["warnings"] == ["LLM evaluation skipped"]
        assert d["rule_warnings"] == {"RuleA": ["LLM evaluation skipped"]}
        assert result.has_warnings is True

    def test_to_dict_preserves_match_evidence(self):
        """Test serialization keeps all rule match evidence."""
        match = RuleMatch(
            rule_name="LLMRule",
            meta={"category": "test"},
            action=Action.FLAG,
            severity="medium",
            source_file="/rules/test.nov",
            matching_keywords={"$keyword": True},
            matching_semantics={"$semantic": True},
            matching_llm={"$judge": True},
            semantic_scores={"$semantic": 0.81},
            llm_scores={"$judge": 0.92},
            matched_patterns=["$keyword", "$semantic", "$judge"],
        )
        result = ScanResult(
            original_text="test input",
            sanitized_text="test input",
            matches=[match],
        )

        match_dict = result.to_dict()["matches"][0]

        assert match_dict["source_file"] == "/rules/test.nov"
        assert match_dict["matching_keywords"] == {"$keyword": True}
        assert match_dict["matching_semantics"] == {"$semantic": True}
        assert match_dict["matching_llm"] == {"$judge": True}
        assert match_dict["semantic_scores"] == {"$semantic": 0.81}
        assert match_dict["llm_scores"] == {"$judge": 0.92}
        assert match_dict["matched_patterns"] == ["$keyword", "$semantic", "$judge"]

    def test_bool_conversion(self):
        """Test boolean conversion."""
        empty = ScanResult(original_text="test", sanitized_text="test")
        assert bool(empty) is False

        with_match = ScanResult(
            original_text="test",
            sanitized_text="test",
            matches=[RuleMatch(rule_name="Test", meta={}, action=Action.FLAG, severity=None)]
        )
        assert bool(with_match) is True


# =============================================================================
# Redaction Tests
# =============================================================================

class TestRedactor:
    """Tests for Redactor class."""

    def test_simple_pattern_redaction(self):
        """Test redacting a simple pattern."""
        redactor = Redactor()
        result = redactor.redact_patterns(
            "My password is secret123",
            ["secret123"]
        )
        assert "secret123" not in result.text
        assert "[REDACTED]" in result.text
        assert len(result.redactions) == 1

    def test_regex_pattern_redaction(self):
        """Test redacting regex patterns."""
        redactor = Redactor()
        result = redactor.redact_patterns(
            "Contact me at test@example.com",
            [r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}']
        )
        assert "test@example.com" not in result.text
        assert len(result.redactions) == 1

    def test_pii_redaction(self):
        """Test built-in PII pattern redaction."""
        redactor = Redactor()
        result = redactor.redact_pii(
            "Email: user@test.com, Phone: 555-123-4567",
            pii_types=["email", "phone"]
        )
        assert "user@test.com" not in result.text
        assert "555-123-4567" not in result.text
        assert len(result.redactions) == 2

    def test_custom_marker(self):
        """Test custom redaction marker."""
        redactor = Redactor(marker="***")
        result = redactor.redact_patterns("secret data", ["secret"])
        assert "***" in result.text

    def test_preserve_length(self):
        """Test length-preserving redaction."""
        redactor = Redactor(marker="*", preserve_length=True)
        result = redactor.redact_patterns("secret", ["secret"])
        assert result.text == "******"

    def test_multiple_patterns(self):
        """Test redacting multiple patterns."""
        redactor = Redactor()
        result = redactor.redact_patterns(
            "username: admin, password: secret",
            ["admin", "secret"]
        )
        assert "admin" not in result.text
        assert "secret" not in result.text
        assert len(result.redactions) == 2

    def test_keyword_redaction_treats_literal_keywords_as_literals(self):
        """Test literal keyword redaction does not treat metacharacters as regex."""
        redactor = Redactor()
        result = redactor.redact_keywords(
            "apiXkey and api.key",
            {"$secret": True},
            {"$secret": KeywordPattern(pattern="api.key", is_regex=False)},
        )

        assert result.text == "apiXkey and [REDACTED]"
        assert result.redactions[0]["original"] == "api.key"
        assert result.redactions[0]["is_regex"] is False

    def test_keyword_redaction_respects_case_sensitive_keywords(self):
        """Test keyword redaction honors case-sensitive keyword patterns."""
        redactor = Redactor()
        result = redactor.redact_keywords(
            "secret Secret",
            {"$secret": True},
            {"$secret": KeywordPattern(pattern="Secret", case_sensitive=True)},
        )

        assert result.text == "secret [REDACTED]"
        assert len(result.redactions) == 1
        assert result.redactions[0]["original"] == "Secret"
        assert result.redactions[0]["case_sensitive"] is True

    def test_keyword_redaction_preserves_regex_keyword_semantics(self):
        """Test regex keyword redaction still uses regex matching."""
        redactor = Redactor()
        result = redactor.redact_keywords(
            "token=abc123 token=xyz456",
            {"$token": True},
            {"$token": KeywordPattern(pattern=r"token=\w+", is_regex=True)},
        )

        assert result.text == "[REDACTED] [REDACTED]"
        assert len(result.redactions) == 2
        assert all(redaction["is_regex"] for redaction in result.redactions)
