"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia 
twitter: @fr0gger_
License: MIT License
Version: 1.0.0
Description: Base evaluator interfaces for Nova pattern matching
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Tuple, Union


class BaseEvaluator(ABC):
    """Base class for all pattern evaluators."""
    
    @abstractmethod
    def evaluate(self, pattern: Any, text: str) -> Union[bool, Tuple[bool, float]]:
        """
        Evaluate if a pattern matches a text.
        
        Args:
            pattern: The pattern to match against
            text: The text to evaluate
            
        Returns:
            Boolean indicating match success or tuple of (success, confidence)
        """
        pass


class KeywordEvaluator(BaseEvaluator):
    """Base class for keyword pattern evaluators."""
    pass

class FuzzyEvaluator(BaseEvaluator):
    """Base class for fuzzy pattern evaluators."""
    pass


class SemanticEvaluator(BaseEvaluator):
    """Base class for semantic pattern evaluators."""
    pass


class LLMEvaluator(BaseEvaluator):
    """Base class for LLM pattern evaluators."""
    
    @abstractmethod
    def evaluate_prompt(self, prompt_template: str, text: str) -> Tuple[bool, float, Dict[str, Any]]:
        """
        Evaluate a text using an LLM prompt template.
        
        Args:
            prompt_template: The prompt to send to the LLM
            text: The text to evaluate
            
        Returns:
            Tuple of (matched, confidence, details)
        """
        pass