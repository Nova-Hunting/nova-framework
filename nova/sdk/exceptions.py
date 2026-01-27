"""
Nova SDK Exceptions

Custom exceptions for the Nova SDK.
"""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .result import ScanResult


class NovaSDKError(Exception):
    """Base exception for Nova SDK."""
    pass


class NovaBlockedError(NovaSDKError):
    """
    Raised when a request is blocked by policy.

    Attributes:
        result: The ScanResult that triggered the block
        message: Human-readable error message
    """

    def __init__(self, result: "ScanResult", message: Optional[str] = None):
        self.result = result
        self.message = message or self._build_message()
        super().__init__(self.message)

    def _build_message(self) -> str:
        """Build default error message from result."""
        blocked_rules = [m.rule_name for m in self.result.matches]
        if blocked_rules:
            return f"Request blocked by Nova: {', '.join(blocked_rules)}"
        return "Request blocked by Nova policy"


class NovaConfigError(NovaSDKError):
    """Raised for configuration errors."""
    pass


class NovaRedactionError(NovaSDKError):
    """Raised when redaction fails."""
    pass


class NovaParseError(NovaSDKError):
    """Raised when rule parsing fails."""
    pass
