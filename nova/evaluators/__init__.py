"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia
twitter: @fr0gger_
License: MIT License
Version: see nova._version
Description: Evaluator module initialization

NOTE: Heavy ML imports (transformers, torch, sentence-transformers) are done lazily
when actually needed. This avoids ~1 second import overhead for keyword-only matching.
The transformers configuration for clean_up_tokenization_spaces is done in
nova/evaluators/semantics.py when the semantic model is first loaded.
"""

# Lightweight imports - always available
from nova.evaluators.base import BaseEvaluator, KeywordEvaluator, SemanticEvaluator, LLMEvaluator
from nova.evaluators.keywords import DefaultKeywordEvaluator
from nova.evaluators.condition import evaluate_condition

# Lazy imports for heavy ML modules - only load when accessed
_DefaultSemanticEvaluator = None
_OpenAIEvaluator = None
_OpenRouterEvaluator = None


def __getattr__(name):
    """Lazy loading of heavy evaluator classes."""
    global _DefaultSemanticEvaluator, _OpenAIEvaluator, _OpenRouterEvaluator

    if name == 'DefaultSemanticEvaluator':
        if _DefaultSemanticEvaluator is None:
            from nova.evaluators.semantics import DefaultSemanticEvaluator as _DSE
            _DefaultSemanticEvaluator = _DSE
        return _DefaultSemanticEvaluator

    if name == 'OpenAIEvaluator':
        if _OpenAIEvaluator is None:
            from nova.evaluators.llm import OpenAIEvaluator as _OAE
            _OpenAIEvaluator = _OAE
        return _OpenAIEvaluator

    if name == 'OpenRouterEvaluator':
        if _OpenRouterEvaluator is None:
            from nova.evaluators.llm import OpenRouterEvaluator as _ORE
            _OpenRouterEvaluator = _ORE
        return _OpenRouterEvaluator

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    'BaseEvaluator',
    'KeywordEvaluator',
    'SemanticEvaluator',
    'LLMEvaluator',
    'DefaultKeywordEvaluator',
    'DefaultSemanticEvaluator',
    'OpenAIEvaluator',
    'OpenRouterEvaluator',
    'evaluate_condition',
]
