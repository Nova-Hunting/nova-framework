"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia
twitter: @fr0gger_
License: MIT License
Version: see nova._version
Description: Shared LLM evaluator infrastructure (model selection, caching, HTTP session)
"""

import os
import time
import hashlib
import threading
from collections import OrderedDict
from typing import Dict, Optional, Tuple, Any

import requests

from nova.utils.logger import get_logger

# Get logger for this module
logger = get_logger("nova.evaluators.llm")

PROVIDER_MODEL_ENV = {
    "openai": "OPENAI_LLM_MODEL",
    "anthropic": "ANTHROPIC_LLM_MODEL",
    "azure": "AZURE_OPENAI_LLM_MODEL",
    "ollama": "OLLAMA_LLM_MODEL",
    "groq": "GROQ_LLM_MODEL",
    "openrouter": "OPENROUTER_LLM_MODEL",
}

PROVIDER_MODEL_ENV_ALIASES = {
    "azure": ("AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_MODEL"),
    "openai": ("OPENAI_MODEL",),
    "anthropic": ("ANTHROPIC_MODEL",),
    "groq": ("GROQ_MODEL",),
    "ollama": ("OLLAMA_MODEL",),
    "openrouter": ("OPENROUTER_MODEL",),
}


def _get_env_model(llm_type: str) -> Optional[str]:
    env_names = [PROVIDER_MODEL_ENV.get(llm_type.lower())]
    env_names.extend(PROVIDER_MODEL_ENV_ALIASES.get(llm_type.lower(), ()))
    env_names.append("NOVA_LLM_MODEL")

    for env_name in env_names:
        if env_name and os.environ.get(env_name):
            return os.environ[env_name]
    return None


def _select_model(llm_type: str, explicit_model: Optional[str], default_model: str) -> str:
    return explicit_model or _get_env_model(llm_type) or default_model


class TTLLRUCache(OrderedDict):
    """
    LRU cache with TTL support and O(1) eviction.

    Uses OrderedDict to maintain insertion order, enabling O(1) eviction
    of the oldest entry (vs O(n log n) for sorting-based approaches).
    Also supports time-based expiration via TTL.
    """

    def __init__(self, maxsize: int = 1000, ttl: float = 300.0):
        """
        Initialize the cache.

        Args:
            maxsize: Maximum number of entries in the cache
            ttl: Time-to-live in seconds for cache entries
        """
        super().__init__()
        self.maxsize = maxsize
        self.ttl = ttl
        self._timestamps = {}  # Separate dict for timestamps to avoid nested access

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Get a value from the cache, checking TTL expiration.
        Moves accessed item to end (most recently used).

        Returns:
            The cached value or None if not found/expired
        """
        if key not in self:
            return None

        # Check TTL expiration
        if time.time() - self._timestamps.get(key, 0) >= self.ttl:
            # Expired - remove and return None
            del self[key]
            self._timestamps.pop(key, None)
            return None

        # Move to end (most recently used) and return
        self.move_to_end(key)
        return OrderedDict.__getitem__(self, key)

    def set(self, key: str, value: Dict[str, Any]) -> None:
        """
        Set a value in the cache with automatic LRU eviction.

        O(1) eviction by removing from front of OrderedDict.
        """
        # If key exists, move to end
        if key in self:
            self.move_to_end(key)

        # Store value and timestamp
        OrderedDict.__setitem__(self, key, value)
        self._timestamps[key] = time.time()

        # Evict oldest entries if over capacity (O(1) per eviction)
        while len(self) > self.maxsize:
            oldest_key = next(iter(self))
            del self[oldest_key]
            self._timestamps.pop(oldest_key, None)

    def __delitem__(self, key):
        """Override to also clean up timestamp."""
        OrderedDict.__delitem__(self, key)
        self._timestamps.pop(key, None)

    def clear(self):
        """Clear both the cache and timestamps."""
        OrderedDict.clear(self)
        self._timestamps.clear()


# Lazy-initialized shared session for connection reuse across all evaluators
# This prevents repeated SSL handshakes and TCP connection establishment
_SHARED_SESSION = None

# Global LLM response cache for avoiding duplicate API calls
# Uses TTLLRUCache for O(1) eviction instead of O(n log n) sorting
_LLM_RESPONSE_CACHE = TTLLRUCache(maxsize=1000, ttl=300.0)

# Threading locks for thread-safe cache and session access
_LLM_CACHE_LOCK = threading.Lock()
_SESSION_LOCK = threading.Lock()


def _normalize_cache_temperature(temperature: float) -> str:
    """Normalize temperature for stable cache keys."""
    try:
        return f"{float(temperature):.8g}"
    except (TypeError, ValueError):
        return str(temperature)


def _get_llm_cache_key(prompt: str, text: str, model: str, temperature: float) -> str:
    """Create a cache key from prompt+text+model+temperature combination.

    Includes content lengths to reduce collision probability when using
    truncated hash. Format: len(prompt):len(text):hash[:24]
    """
    content = f"{prompt}|{text}|{model}|temperature:{_normalize_cache_temperature(temperature)}"
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:24]
    return f"{len(prompt)}:{len(text)}:{content_hash}"


def _get_cached_response(prompt: str, text: str, model: str, temperature: float) -> Optional[Tuple[bool, float, Dict[str, Any]]]:
    """Check if we have a valid cached response for this evaluation (thread-safe)."""
    cache_key = _get_llm_cache_key(prompt, text, model, temperature)
    with _LLM_CACHE_LOCK:
        cached = _LLM_RESPONSE_CACHE.get(cache_key)
        if cached is not None:
            # Return cached result with cache_hit flag
            details = {**cached['details'], 'cache_hit': True}
            return cached['matched'], cached['confidence'], details
    return None


def _cache_response(prompt: str, text: str, model: str, temperature: float, matched: bool, confidence: float, details: Dict[str, Any]) -> None:
    """Cache an LLM response for future use (thread-safe with O(1) eviction)."""
    cache_key = _get_llm_cache_key(prompt, text, model, temperature)
    with _LLM_CACHE_LOCK:
        _LLM_RESPONSE_CACHE.set(cache_key, {
            'matched': matched,
            'confidence': confidence,
            'details': details
        })


def _get_shared_session():
    """Lazy initialization of shared session - only creates when first needed (thread-safe)."""
    global _SHARED_SESSION
    if _SHARED_SESSION is None:
        with _SESSION_LOCK:
            # Double-check after acquiring lock
            if _SHARED_SESSION is None:
                _SHARED_SESSION = requests.Session()
                # Configure session for optimal reuse (keep connections alive)
                _SHARED_SESSION.mount('https://', requests.adapters.HTTPAdapter(
                    pool_connections=20,  # Number of connection objects to keep in pool
                    pool_maxsize=20,      # Maximum number of connections in the pool
                    max_retries=3,        # Auto-retry failed requests
                    pool_block=False      # Don't block when pool is depleted
                ))
    return _SHARED_SESSION
