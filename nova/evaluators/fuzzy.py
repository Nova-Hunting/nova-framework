import re
from typing import Dict, Union
from nova.core.rules import KeywordPattern
from nova.evaluators.base import FuzzyEvaluator
from nova.utils.logger import get_logger
try:
    from rapidfuzz import fuzz
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    RAPIDFUZZ_AVAILABLE = False
    fuzz = None

# Get logger for this module
logger = get_logger("nova.evaluators.fuzzy")


class DefaultFuzzyEvaluator(FuzzyEvaluator):
    """Default fuzzy pattern evaluator supporting case sensitivity."""
    
    def __init__(self):
        if not RAPIDFUZZ_AVAILABLE:
            logger.error("RapidFuzz library not found. Fuzzy matching will fail. Install with: pip install rapidfuzz")

    
    def evaluate(self, pattern: KeywordPattern, text: str, key: str = None) -> bool:
        """
        Check if a fuzzy pattern matches the text.
        
        Args:
            pattern: The FuzzyPattern to match
            text: The text to evaluate
            
        Returns:
            Boolean indicating whether the pattern matches
        """

        if not RAPIDFUZZ_AVAILABLE or fuzz is None:
            return False

        if not text or not pattern.pattern:
            return False

        target = pattern.pattern
        content = text
        
        #Handle Case Sensitivity
        if not pattern.case_sensitive:
            target = target.lower()
            content = content.lower()

        #Calculate Score
        # partial_ratio is best for "needle in haystack"
        # It detects "admin" inside "I am administrator" with score 100
        score = fuzz.partial_ratio(target, content)

        is_match = (score >= pattern.threshold)
        return is_match

        