"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia
twitter: @fr0gger_
License: MIT License
Version: see nova._version
Description: Keyword pattern evaluator implementations
"""

import re
from typing import Dict, Union
from nova.core.rules import KeywordPattern

try:  # Optional fuzzy matching backend
    from rapidfuzz import fuzz as _rf_fuzz
except ImportError:  # pragma: no cover - exercised via fallback tests
    _rf_fuzz = None
from nova.evaluators.base import KeywordEvaluator
from nova.utils.logger import get_logger

# Get logger for this module
logger = get_logger("nova.evaluators.keywords")


class DefaultKeywordEvaluator(KeywordEvaluator):
    """Default keyword pattern evaluator supporting regex and case sensitivity."""
    
    def __init__(self):
        """Initialize the evaluator with cached compiled patterns."""
        self._compiled_patterns: Dict[str, Union[re.Pattern, None]] = {}
    
    def compile_pattern(self, key: str, pattern: KeywordPattern) -> None:
        """
        Compile a regex pattern and cache it.
        
        Args:
            key: Unique identifier for the pattern
            pattern: The KeywordPattern to compile
        """
        if pattern.is_regex:
            flags = 0 if pattern.case_sensitive else re.IGNORECASE
            try:
                self._compiled_patterns[key] = re.compile(pattern.pattern, flags)
            except re.error as e:
                logger.warning(f"Invalid regex pattern for {key}: {e}")
                self._compiled_patterns[key] = None
        else:
            # No need to compile non-regex patterns
            self._compiled_patterns[key] = None
    
    def evaluate(self, pattern: KeywordPattern, text: str, key: str = None) -> bool:
        """
        Check if a keyword pattern matches the text.

        Args:
            pattern: The KeywordPattern to match
            text: The text to evaluate
            key: Optional pattern key for cached regex patterns

        Returns:
            Boolean indicating whether the pattern matches
        """
        # Input validation - handle None/empty text gracefully
        if text is None or not isinstance(text, str):
            return False
        if not text.strip():
            return False

        if pattern.is_regex:
            # Try to use cached pattern if key is provided
            compiled_pattern = None
            if key and key in self._compiled_patterns:
                compiled_pattern = self._compiled_patterns[key]
            
            # Compile on the fly if not cached
            if compiled_pattern is None and key:
                self.compile_pattern(key, pattern)
                compiled_pattern = self._compiled_patterns.get(key)
            
            # Fall back to direct compilation if still no cached pattern
            if compiled_pattern is None:
                flags = 0 if pattern.case_sensitive else re.IGNORECASE
                try:
                    compiled_pattern = re.compile(pattern.pattern, flags)
                except re.error:
                    return False
            
            # Try to match using the compiled pattern
            if compiled_pattern:
                return bool(compiled_pattern.search(text))
            else:
                return False
        else:
            needle = pattern.pattern if pattern.case_sensitive else pattern.pattern.lower()
            haystack = text if pattern.case_sensitive else text.lower()

            # Exact substring match always wins
            if needle in haystack:
                return True

            if pattern.fuzzy_threshold is None:
                return False

            return self._fuzzy_match(needle, haystack, pattern.fuzzy_threshold)

    @staticmethod
    def fuzzy_score(needle: str, haystack: str) -> float:
        """
        Best-alignment similarity (0.0-1.0) of needle against any substring of
        haystack, using normalized Indel distance (rapidfuzz partial_ratio).
        Falls back to difflib if rapidfuzz is not installed.
        """
        if not needle or not haystack:
            return 0.0
        if _rf_fuzz is not None:
            return _rf_fuzz.partial_ratio(needle, haystack) / 100.0

        # Pure-Python fallback: slide a needle-sized window over the haystack.
        import difflib
        n = len(needle)
        if len(haystack) <= n:
            return difflib.SequenceMatcher(None, needle, haystack).ratio()
        best = 0.0
        for i in range(len(haystack) - n + 1):
            r = difflib.SequenceMatcher(None, needle, haystack[i:i + n]).ratio()
            if r > best:
                best = r
                if best == 1.0:
                    break
        return best

    def _fuzzy_match(self, needle: str, haystack: str, threshold: float) -> bool:
        score = self.fuzzy_score(needle, haystack)
        matched = score >= threshold
        if matched:
            logger.debug(f"Fuzzy keyword match: '{needle}' score={score:.3f} >= {threshold}")
        return matched