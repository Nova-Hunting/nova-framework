"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia
twitter: @fr0gger_
License: MIT License
Version: see nova._version
Description: LLM-based evaluator implementations

This package preserves the historical public import path
``nova.evaluators.llm``. Provider implementations live in internal
modules (``_openai``, ``_anthropic``, ``_groq``, ``_ollama``) with shared
caching/session infrastructure in ``_shared`` and the evaluator factory
in ``_factory``. Import everything from ``nova.evaluators.llm`` directly;
the underscore-prefixed modules are implementation details.
"""

from nova.evaluators.llm._shared import (
    PROVIDER_MODEL_ENV,
    PROVIDER_MODEL_ENV_ALIASES,
    TTLLRUCache,
    logger,
)
from nova.evaluators.llm._shared import _get_env_model as _get_env_model
from nova.evaluators.llm._shared import _select_model as _select_model
from nova.evaluators.llm._shared import _LLM_RESPONSE_CACHE as _LLM_RESPONSE_CACHE
from nova.evaluators.llm._shared import _LLM_CACHE_LOCK as _LLM_CACHE_LOCK
from nova.evaluators.llm._shared import _SESSION_LOCK as _SESSION_LOCK
from nova.evaluators.llm._shared import _normalize_cache_temperature as _normalize_cache_temperature
from nova.evaluators.llm._shared import _get_llm_cache_key as _get_llm_cache_key
from nova.evaluators.llm._shared import _get_cached_response as _get_cached_response
from nova.evaluators.llm._shared import _cache_response as _cache_response
from nova.evaluators.llm._shared import _get_shared_session as _get_shared_session
from nova.evaluators.llm._openai import (
    OpenAIEvaluator,
    OpenRouterEvaluator,
    AzureOpenAIEvaluator,
)
from nova.evaluators.llm._anthropic import AnthropicEvaluator
from nova.evaluators.llm._groq import GroqEvaluator
from nova.evaluators.llm._ollama import OllamaEvaluator
from nova.evaluators.llm._factory import get_validated_evaluator
from nova.evaluators.base import LLMEvaluator

__all__ = [
    'PROVIDER_MODEL_ENV',
    'PROVIDER_MODEL_ENV_ALIASES',
    'TTLLRUCache',
    'logger',
    'LLMEvaluator',
    'OpenAIEvaluator',
    'OpenRouterEvaluator',
    'AzureOpenAIEvaluator',
    'AnthropicEvaluator',
    'GroqEvaluator',
    'OllamaEvaluator',
    'get_validated_evaluator',
]
