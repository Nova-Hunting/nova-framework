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
            # Simple string matching based on case sensitivity
            if pattern.case_sensitive:
                return pattern.pattern in text
            else:
                return pattern.pattern.lower() in text.lower()