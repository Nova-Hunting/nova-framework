"""
Nova SDK - High-level API for prompt pattern matching.

Provides policy-based scanning with configurable actions (block/redact/flag/allow),
decorator patterns for protecting functions, and automatic redaction capabilities.

Example:
    from nova.sdk import Nova, Action

    # First clone the rules: git clone https://github.com/Nova-Hunting/nova-rules

    # Initialize with rules and policy
    nova = Nova(
        rules_path="nova-rules/",  # Path to cloned nova-rules repository
        policy={
            "PI": {"action": "block"},
            "PII": {"action": "redact"},
            "JB": {"action": "flag"},
        },
        llm_provider="anthropic"
    )

    # Scan a prompt
    result = nova.scan(user_input)
    if result.blocked:
        print("Blocked!")
    else:
        clean_text = result.sanitized_text

    # Use decorator
    @nova.protect(action="block", severity="critical")
    def chat(prompt):
        return llm.generate(prompt)

    # Standalone decorator (auto-creates Nova instance)
    from nova.sdk import protect

    @protect(rules_path="nova-rules/", action="block")  # Path to cloned nova-rules
    def protected_chat(prompt):
        return llm.generate(prompt)
"""

from .nova import Nova
from .result import ScanResult, RuleMatch
from .policy import NovaPolicy, PolicyRule, Action
from .redaction import Redactor, RedactionResult
from .exceptions import (
    NovaSDKError,
    NovaBlockedError,
    NovaConfigError,
    NovaRedactionError,
    NovaParseError
)
from .decorator import (
    protect,
    scan,
    scan_async,
    get_default_nova,
    set_default_nova
)

__all__ = [
    # Main class
    "Nova",

    # Result classes
    "ScanResult",
    "RuleMatch",

    # Policy classes
    "NovaPolicy",
    "PolicyRule",
    "Action",

    # Redaction
    "Redactor",
    "RedactionResult",

    # Exceptions
    "NovaSDKError",
    "NovaBlockedError",
    "NovaConfigError",
    "NovaRedactionError",
    "NovaParseError",

    # Standalone functions
    "protect",
    "scan",
    "scan_async",
    "get_default_nova",
    "set_default_nova",
]
