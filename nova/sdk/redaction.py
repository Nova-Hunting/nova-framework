"""
Nova SDK Redaction System

Pattern-based text redaction for sensitive content removal.
"""

import re
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


@dataclass
class RedactionResult:
    """Result of a redaction operation."""
    text: str
    redactions: List[Dict[str, Any]] = field(default_factory=list)


class Redactor:
    """
    Pattern-based text redaction system.

    Supports:
    - Redacting matched keywords from Nova rules
    - Redacting by regex pattern
    - Built-in PII pattern redaction
    - Custom redaction markers

    Example:
        redactor = Redactor(marker="[REDACTED]")
        result = redactor.redact_patterns(text, [r"password=\\w+"])
        print(result.text)  # Text with passwords redacted
    """

    DEFAULT_MARKER = "[REDACTED]"

    # Built-in patterns for common PII
    PII_PATTERNS = {
        "email": r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
        "phone": r'\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b',
        "ssn": r'\b\d{3}-\d{2}-\d{4}\b',
        "credit_card": r'\b(?:\d[ -]*?){13,16}\b',
        "ip_address": r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
        "api_key": r'\b(?:api[_-]?key|apikey|access[_-]?token)[=:]\s*["\']?[\w-]{20,}["\']?',
        "password": r'\b(?:password|passwd|pwd)[=:]\s*["\']?[^\s"\']{4,}["\']?',
    }

    def __init__(
        self,
        marker: str = DEFAULT_MARKER,
        preserve_length: bool = False,
        custom_markers: Optional[Dict[str, str]] = None
    ):
        """
        Initialize redactor.

        Args:
            marker: Default replacement text for redactions
            preserve_length: If True, replace with same-length markers
            custom_markers: Map of category -> custom marker text
        """
        self.marker = marker
        self.preserve_length = preserve_length
        self.custom_markers = custom_markers or {}

    def redact_patterns(
        self,
        text: str,
        patterns: List[str],
        category: str = "general"
    ) -> RedactionResult:
        """
        Redact text matching the given patterns.

        Args:
            text: Input text
            patterns: List of regex patterns to redact
            category: Category for marker selection

        Returns:
            RedactionResult with redacted text and details
        """
        result_text = text
        redactions = []
        marker = self.custom_markers.get(category, self.marker)

        # Collect all matches first
        all_matches = []
        for pattern in patterns:
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
                for match in compiled.finditer(text):
                    all_matches.append({
                        "original": match.group(),
                        "start": match.start(),
                        "end": match.end(),
                        "pattern": pattern,
                        "category": category,
                    })
            except re.error:
                # Invalid regex, try literal match
                start = 0
                while True:
                    idx = text.find(pattern, start)
                    if idx == -1:
                        break
                    all_matches.append({
                        "original": pattern,
                        "start": idx,
                        "end": idx + len(pattern),
                        "pattern": pattern,
                        "category": category,
                    })
                    start = idx + 1

        # Remove duplicates and overlapping matches
        all_matches = self._dedupe_matches(all_matches)

        # Apply redactions in reverse order to preserve positions
        for match_info in sorted(all_matches, key=lambda x: x["start"], reverse=True):
            original = match_info["original"]
            if self.preserve_length:
                replacement = marker[0] * len(original) if marker else "*" * len(original)
            else:
                replacement = marker

            match_info["replacement"] = replacement
            redactions.append(match_info)

            result_text = (
                result_text[:match_info["start"]] +
                replacement +
                result_text[match_info["end"]:]
            )

        # Reverse redactions list to match original order
        redactions.reverse()

        return RedactionResult(text=result_text, redactions=redactions)

    def _dedupe_matches(self, matches: List[Dict]) -> List[Dict]:
        """Remove duplicate and overlapping matches, keeping the longest."""
        if not matches:
            return []

        # Sort by start position, then by length (descending)
        sorted_matches = sorted(matches, key=lambda x: (x["start"], -(x["end"] - x["start"])))

        result = []
        last_end = -1

        for match in sorted_matches:
            if match["start"] >= last_end:
                result.append(match)
                last_end = match["end"]

        return result

    def redact_keywords(
        self,
        text: str,
        keyword_matches: Dict[str, bool],
        keyword_patterns: Dict[str, Any],
        category: str = "keyword"
    ) -> RedactionResult:
        """
        Redact matched keywords from Nova rule results.

        Args:
            text: Input text
            keyword_matches: Dict of matched keywords from scan (var_name -> bool)
            keyword_patterns: Original KeywordPattern objects from rule
            category: Category for marker selection

        Returns:
            RedactionResult with redacted text and details
        """
        patterns_to_redact = []

        for var_name, matched in keyword_matches.items():
            if matched:
                # Handle both with and without $ prefix
                clean_name = var_name.lstrip('$')
                for key, pattern_obj in keyword_patterns.items():
                    clean_key = key.lstrip('$')
                    if clean_key == clean_name:
                        patterns_to_redact.append(pattern_obj.pattern)
                        break

        return self.redact_patterns(text, patterns_to_redact, category)

    def redact_pii(
        self,
        text: str,
        pii_types: Optional[List[str]] = None
    ) -> RedactionResult:
        """
        Redact common PII patterns.

        Args:
            text: Input text
            pii_types: List of PII types to redact (default: all)
                       Options: email, phone, ssn, credit_card, ip_address, api_key, password

        Returns:
            RedactionResult with redacted text and details
        """
        types_to_redact = pii_types or list(self.PII_PATTERNS.keys())
        patterns = [
            self.PII_PATTERNS[t]
            for t in types_to_redact
            if t in self.PII_PATTERNS
        ]

        return self.redact_patterns(text, patterns, category="PII")

    def redact_all(
        self,
        text: str,
        patterns: Optional[List[str]] = None,
        include_pii: bool = True,
        pii_types: Optional[List[str]] = None
    ) -> RedactionResult:
        """
        Redact using both custom patterns and PII patterns.

        Args:
            text: Input text
            patterns: Custom patterns to redact
            include_pii: Whether to include PII patterns
            pii_types: Specific PII types to include

        Returns:
            RedactionResult with all redactions applied
        """
        all_patterns = list(patterns) if patterns else []

        if include_pii:
            types_to_redact = pii_types or list(self.PII_PATTERNS.keys())
            for t in types_to_redact:
                if t in self.PII_PATTERNS:
                    all_patterns.append(self.PII_PATTERNS[t])

        return self.redact_patterns(text, all_patterns, category="mixed")
