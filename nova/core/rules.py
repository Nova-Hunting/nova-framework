"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia 
twitter: @fr0gger_
License: MIT License
Version: 1.0.0
Description: Rule definitions and pattern classes for pattern matching
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Union, Tuple, Any


@dataclass
class KeywordPattern:
    """
    Pattern for keyword-based matching with support for regex and case sensitivity.
    
    Attributes:
        pattern: The string or regex pattern to match
        is_regex: Whether the pattern should be treated as a regular expression
        case_sensitive: Whether the match should be case-sensitive
    """
    pattern: str
    is_regex: bool = False
    case_sensitive: bool = False  # Default to case-insensitive
    is_fuzzy: bool = False 
    threshold: int = 80  


@dataclass
class FuzzyPattern:
    """
    Pattern for fuzzy matching with support for regex and case sensitivity.
    
    Attributes:
        pattern: The string or regex pattern to match
        case_sensitive: Whether the match should be case-sensitive
    """
    pattern: str
    threshold: float
    case_sensitive: bool = False  # Default to case-insensitive


@dataclass
class SemanticPattern:
    """
    Pattern for semantic similarity matching.
    
    Attributes:
        pattern: The reference text for semantic comparison
        threshold: The minimum similarity score to consider a match (0.0 to 1.0)
    """
    pattern: str
    threshold: float = 0.1  # Default threshold


@dataclass
class LLMPattern:
    """
    Pattern for LLM-based evaluation.
    
    Attributes:
        pattern: The prompt template for LLM evaluation
        threshold: The minimum confidence score to consider a match (0.0 to 1.0)
    """
    pattern: str
    threshold: float = 0.1  # Default confidence threshold


@dataclass
class NovaRule:
    """
    Complete rule definition containing patterns and condition logic.
    
    Attributes:
        name: The name of the rule
        meta: Metadata key-value pairs
        keywords: Dictionary of keyword patterns
        semantics: Dictionary of semantic patterns
        llms: Dictionary of LLM patterns
        condition: Logical condition for combining pattern matches
    """
    name: str
    meta: Dict[str, str] = field(default_factory=dict)
    keywords: Dict[str, KeywordPattern] = field(default_factory=dict)
    semantics: Dict[str, SemanticPattern] = field(default_factory=dict)
    llms: Dict[str, LLMPattern] = field(default_factory=dict)
    fuzzy: Dict[str , FuzzyPattern] = field(default_factory=dict)
    condition: str = ""