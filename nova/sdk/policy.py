"""
Nova SDK Policy System

Provides policy-based action configuration for Nova rule matches.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union, Callable, Any


class Action(Enum):
    """Actions that can be taken when a policy rule matches."""
    ALLOW = "allow"      # Allow the request to proceed
    FLAG = "flag"        # Flag for review but allow
    REDACT = "redact"    # Redact sensitive content and continue
    BLOCK = "block"      # Block the request entirely


@dataclass
class PolicyRule:
    """Individual policy rule configuration."""
    action: Action = Action.FLAG
    severity: Optional[str] = None
    message: Optional[str] = None
    callback: Optional[Callable[[Any], Any]] = None


class NovaPolicy:
    """
    Policy configuration for mapping Nova rules to actions.

    Supports multiple matching strategies:
    1. By exact rule name: "DANJailbreak" matches exactly
    2. By rule name prefix: "PI" matches PromptInjectionJailbreak
    3. By category: "jailbreak/*" matches all jailbreak rules
    4. By severity: Can set defaults by severity level

    Example:
        policy = NovaPolicy({
            "PI": {"action": "block", "severity": "critical"},
            "PII": {"action": "redact"},
            "jailbreak/*": {"action": "flag"},
        })
    """

    DEFAULT_SEVERITY_ACTIONS = {
        "critical": Action.BLOCK,
        "high": Action.BLOCK,
        "medium": Action.FLAG,
        "low": Action.ALLOW,
    }

    def __init__(
        self,
        rules: Optional[Dict[str, Union[Dict, PolicyRule]]] = None,
        default_action: Action = Action.FLAG,
        severity_actions: Optional[Dict[str, Action]] = None
    ):
        """
        Initialize policy.

        Args:
            rules: Mapping of pattern -> PolicyRule or dict config
            default_action: Default action when no rule matches
            severity_actions: Map severity levels to actions
        """
        self.rules: Dict[str, PolicyRule] = {}
        self.default_action = default_action
        self.severity_actions = severity_actions or self.DEFAULT_SEVERITY_ACTIONS.copy()

        if rules:
            for pattern, config in rules.items():
                self.add_rule(pattern, config)

    def add_rule(self, pattern: str, config: Union[Dict, PolicyRule]) -> None:
        """
        Add a policy rule for a pattern.

        Args:
            pattern: Pattern to match (rule name, prefix, or category wildcard)
            config: PolicyRule or dict with action, severity, message, callback
        """
        if isinstance(config, PolicyRule):
            self.rules[pattern] = config
        else:
            action_str = config.get("action", "flag")
            action = Action(action_str) if isinstance(action_str, str) else action_str
            self.rules[pattern] = PolicyRule(
                action=action,
                severity=config.get("severity"),
                message=config.get("message"),
                callback=config.get("callback")
            )

    def get_action_for_match(
        self,
        rule_name: str,
        rule_meta: Dict[str, str]
    ) -> PolicyRule:
        """
        Determine action for a matched rule.

        Matching priority:
        1. Exact rule name match
        2. Rule name prefix match (e.g., "PI" -> "PromptInjection*")
        3. Category match (e.g., "jailbreak/*")
        4. Severity-based default
        5. Global default

        Args:
            rule_name: Name of the matched rule
            rule_meta: Metadata dict from the rule

        Returns:
            PolicyRule with action to take
        """
        # 1. Exact match
        if rule_name in self.rules:
            return self.rules[rule_name]

        # 2. Prefix match - check if any policy key is prefix of rule name
        rule_name_lower = rule_name.lower()
        for pattern, policy_rule in self.rules.items():
            if not pattern.endswith("*") and not pattern.endswith("/*"):
                # Simple prefix match (case-insensitive)
                if rule_name_lower.startswith(pattern.lower()):
                    return policy_rule

        # 3. Category match
        rule_category = rule_meta.get("category", "")
        for pattern, policy_rule in self.rules.items():
            if pattern.endswith("/*"):
                # Category wildcard match
                category_prefix = pattern[:-2]
                if rule_category.startswith(category_prefix):
                    return policy_rule
            elif pattern.endswith("*"):
                # General wildcard
                prefix = pattern[:-1]
                if rule_category.startswith(prefix) or rule_name.startswith(prefix):
                    return policy_rule

        # 4. Severity-based default
        rule_severity = rule_meta.get("severity", "").lower()
        if rule_severity in self.severity_actions:
            return PolicyRule(action=self.severity_actions[rule_severity])

        # 5. Global default
        return PolicyRule(action=self.default_action)

    def set_severity_action(self, severity: str, action: Action) -> None:
        """Set the default action for a severity level."""
        self.severity_actions[severity.lower()] = action

    def set_default_action(self, action: Action) -> None:
        """Set the global default action."""
        self.default_action = action
