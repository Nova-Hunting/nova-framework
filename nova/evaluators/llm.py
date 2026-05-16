"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia
twitter: @fr0gger_
License: MIT License
Version: see nova._version
Description: LLM-based evaluator implementations
"""

import os
import json
import requests
import re
import time
import hashlib
import threading
from collections import OrderedDict
from typing import Dict, Optional, Tuple, Any, Union
from nova.evaluators.base import LLMEvaluator
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


class OpenAIEvaluator(LLMEvaluator):
    """
    LLM evaluator using OpenAI's API.
    Evaluates prompts using various OpenAI models.
    """
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini"):
        """
        Initialize the LLM evaluator with API credentials.
        
        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY environment variable)
            model: OpenAI model to use
        """
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model
        self.base_url = "https://api.openai.com/v1/chat/completions"
        self.session = _get_shared_session()  # Use shared session for connection reuse
        self.evaluator_type = "openai"
        self.log_label = "OpenAI"
        
        # Validate API key
        if not self.api_key:
            logger.warning("No API key provided for OpenAI LLM evaluator. Set OPENAI_API_KEY environment variable or pass api_key.")
    
    def evaluate(self, pattern: str, text: str) -> Union[bool, Tuple[bool, float]]:
        """
        Basic evaluate implementation for the BaseEvaluator interface.
        
        Args:
            pattern: The pattern to evaluate
            text: The text to check
            
        Returns:
            Boolean indicating match or tuple of (matched, confidence)
        """
        matched, confidence, _ = self.evaluate_prompt(pattern, text)
        return matched, confidence
    
    def evaluate_prompt(self, prompt_template: str, text: str, temperature: float = 0.1) -> Tuple[bool, float, Dict[str, Any]]:
        """
        Evaluate a text using the provided prompt template with OpenAI API.

        Args:
            prompt_template: The prompt to send to the LLM
            text: The text to evaluate
            temperature: Temperature setting for the model (0.0-1.0)

        Returns:
            Tuple of (matched, confidence, details)
        """
        # Input validation - handle None/empty text gracefully
        if text is None or not isinstance(text, str) or not text.strip():
            return False, 0.0, {"error": "Invalid or empty text"}

        if not self.api_key:
            # No API key available
            return False, 0.0, {"error": "No API key available"}

        # Check cache first
        cache_model = f"{self.evaluator_type}:{self.model}"
        cached = _get_cached_response(prompt_template, text, cache_model, temperature)
        if cached is not None:
            return cached

        try:
            # Format the complete prompt
            full_prompt = (
                f"{prompt_template}\n\n"
                f"Text to evaluate: {text}\n\n"
                f"Respond with a JSON object with keys: matched (boolean), confidence (float 0-1), reason (string)"
            )

            # Call the OpenAI API using the shared session
            response = self.session.post(
                self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system", 
                            "content": "You are a helpful assistant that evaluates text based on the given criteria. "
                                      "Respond with a JSON object containing 'matched' (boolean), 'confidence' (float 0-1), "
                                      "and 'reason' (string)."
                        },
                        {"role": "user", "content": full_prompt}
                    ],
                    "temperature": temperature,  # Use the provided temperature
                    "response_format": {"type": "json_object"}
                },
                timeout=10  # Add timeout for network operations
            )
            
            # Process the response
            if response.status_code == 200:
                result = response.json()
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                
                # Parse the JSON response
                try:
                    evaluation = json.loads(content)
                    matched = bool(evaluation.get("matched", False))
                    confidence = max(0.0, min(1.0, float(evaluation.get("confidence", 0.0))))
                    
                    # Add additional info to the result
                    evaluation["model"] = self.model
                    evaluation["api_status"] = "success"
                    evaluation["evaluator_type"] = self.evaluator_type
                    evaluation["temperature"] = temperature  # Include the temperature used

                    # Cache the successful response
                    _cache_response(prompt_template, text, cache_model, temperature, matched, confidence, evaluation)

                    return matched, confidence, evaluation
                except json.JSONDecodeError as e:
                    logger.error(f"[{self.log_label}] Failed to parse LLM response as JSON.")
                    logger.error(f"[{self.log_label}] JSON error: {e}")
                    logger.error(f"[{self.log_label}] Content type: {type(content)}, length: {len(content) if content else 0}")
                    logger.error(f"[{self.log_label}] Raw content: {repr(content[:1000]) if content else 'EMPTY'}")
                    return False, 0.0, {"error": "Invalid response format", "raw_content": content}
            else:
                error_msg = f"API error: {response.status_code}, {response.text}"
                logger.error(error_msg)
                return False, 0.0, {"error": error_msg, "status_code": response.status_code}

        except requests.Timeout:
            error_msg = "API request timed out"
            logger.error(error_msg)
            return False, 0.0, {"error": error_msg}

        except Exception as e:
            error_msg = f"Error in LLM evaluation: {str(e)}"
            logger.error(error_msg)
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False, 0.0, {"error": error_msg}


class OpenRouterEvaluator(OpenAIEvaluator):
    """
    LLM evaluator using OpenRouter's OpenAI-compatible chat completions API.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "openai/gpt-5.2"):
        """
        Initialize the OpenRouter evaluator with API credentials.

        Args:
            api_key: OpenRouter API key (defaults to OPENROUTER_API_KEY environment variable)
            model: OpenRouter model slug to use
        """
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self.model = model
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.session = _get_shared_session()
        self.evaluator_type = "openrouter"
        self.log_label = "OpenRouter"

        if not self.api_key:
            logger.warning("No API key provided for OpenRouter LLM evaluator. Set OPENROUTER_API_KEY environment variable or pass api_key.")


class GroqEvaluator(LLMEvaluator):
    """
    LLM evaluator using Groq Cloud API.
    Evaluates prompts using various Groq models including safety models.
    Supports both SDK and REST API modes.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "llama-3.3-70b-versatile",
                 use_sdk: bool = True, reasoning_effort: str = "medium"):
        """
        Initialize the LLM evaluator with API credentials.

        Args:
            api_key: Groq API key (defaults to GROQ_API_KEY environment variable)
            model: Groq model to use (defaults to llama-3.3-70b-versatile)
                   For safety model use: "openai/gpt-oss-safeguard-20b"
            use_sdk: Use official Groq SDK (True) or raw requests (False)
            reasoning_effort: Reasoning effort for compatible models ("low", "medium", "high")
        """
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        self.model = model
        self.use_sdk = use_sdk
        self.reasoning_effort = reasoning_effort
        self.base_url = "https://api.groq.com/openai/v1/chat/completions"
        self.session = _get_shared_session()  # Use shared session for connection reuse
        self.client = None

        # Validate API key
        if not self.api_key:
            logger.warning("No API key provided for Groq LLM evaluator. Set GROQ_API_KEY environment variable or pass api_key.")

        # Initialize Groq SDK if requested
        if use_sdk and self.api_key:
            try:
                from groq import Groq
                self.client = Groq(api_key=self.api_key)
            except ImportError:
                logger.warning("Groq SDK not installed. Falling back to REST API. Install with: pip install groq")
                self.use_sdk = False

    def evaluate(self, pattern: str, text: str) -> Union[bool, Tuple[bool, float]]:
        """
        Basic evaluate implementation for the BaseEvaluator interface.

        Args:
            pattern: The pattern to evaluate
            text: The text to check

        Returns:
            Boolean indicating match or tuple of (matched, confidence)
        """
        matched, confidence, _ = self.evaluate_prompt(pattern, text)
        return matched, confidence

    def evaluate_prompt(self, prompt_template: str, text: str, temperature: float = 0.1) -> Tuple[bool, float, Dict[str, Any]]:
        """
        Evaluate a text using the provided prompt template with Groq API.

        Args:
            prompt_template: The prompt to send to the LLM
            text: The text to evaluate
            temperature: Temperature setting for the model (0.0-2.0), note that 0 gets converted to 1e-8

        Returns:
            Tuple of (matched, confidence, details)
        """
        # Input validation - handle None/empty text gracefully
        if text is None or not isinstance(text, str) or not text.strip():
            return False, 0.0, {"error": "Invalid or empty text"}

        if not self.api_key:
            return False, 0.0, {"error": "No API key available"}

        # Use SDK method if available
        if self.use_sdk and self.client:
            return self._evaluate_with_sdk(prompt_template, text, temperature)
        else:
            return self._evaluate_with_rest(prompt_template, text, temperature)

    def _evaluate_with_sdk(self, prompt_template: str, text: str, temperature: float) -> Tuple[bool, float, Dict[str, Any]]:
        """Evaluate using the official Groq SDK with streaming support."""
        # Ensure temperature is within valid range
        if temperature == 0:
            temperature = 1e-8
        elif temperature > 2.0:
            temperature = 2.0

        # Check cache first after provider-specific normalization.
        cache_model = f"groq:{self.model}:reasoning={self.reasoning_effort}"
        cached = _get_cached_response(prompt_template, text, cache_model, temperature)
        if cached is not None:
            return cached

        try:
            # Format the complete prompt with clear structure for JSON output
            full_prompt = (
                f"## Evaluation Criteria\n{prompt_template}\n\n"
                f"## Text to Evaluate\n{text}\n\n"
                f"## Required Response Format\n"
                f"You MUST respond with ONLY a valid JSON object (no markdown, no explanation):\n"
                f'{{"matched": true/false, "confidence": 0.0-1.0, "reason": "brief explanation"}}'
            )

            # Build request parameters - aligned with REST method for consistency
            request_params = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a security evaluation assistant. Your task is to analyze text against "
                            "specific criteria and determine if it matches.\n\n"
                            "CRITICAL: You MUST respond with ONLY a valid JSON object. No markdown formatting, "
                            "no code blocks, no explanation text - just the raw JSON.\n\n"
                            "Response format: {\"matched\": boolean, \"confidence\": float 0-1, \"reason\": string}"
                        )
                    },
                    {"role": "user", "content": full_prompt}
                ],
                "temperature": temperature,
                "max_completion_tokens": 4096,
                "top_p": 1,
                "stream": False,
                "response_format": {"type": "json_object"},
            }

            # Add reasoning_effort for compatible models (like safeguard model)
            if "safeguard" in self.model or "gpt-oss" in self.model:
                request_params["reasoning_effort"] = self.reasoning_effort

            # Call the Groq API using SDK
            completion = self.client.chat.completions.create(**request_params)

            # Process the response
            content = completion.choices[0].message.content

            # Defensive null check before parsing
            if not content or not content.strip():
                logger.error("[Groq SDK] Empty response from API")
                logger.error(f"[Groq SDK] Full completion object: {completion}")
                return False, 0.0, {"error": "Empty response from API"}

            # Parse the JSON response
            try:
                evaluation = json.loads(content)
                matched = bool(evaluation.get("matched", False))
                confidence = max(0.0, min(1.0, float(evaluation.get("confidence", 0.0))))

                # Add additional info to the result
                evaluation["model"] = self.model
                evaluation["api_status"] = "success"
                evaluation["evaluator_type"] = "groq"
                evaluation["temperature"] = temperature
                evaluation["reasoning_effort"] = self.reasoning_effort

                # Cache the successful response
                _cache_response(prompt_template, text, cache_model, temperature, matched, confidence, evaluation)

                return matched, confidence, evaluation
            except json.JSONDecodeError:
                # Try to extract JSON from response if wrapped in text
                json_match = re.search(r'\{[^{}]*\}', content)
                if json_match:
                    try:
                        evaluation = json.loads(json_match.group())
                        matched = bool(evaluation.get("matched", False))
                        confidence = max(0.0, min(1.0, float(evaluation.get("confidence", 0.0))))
                        evaluation["model"] = self.model
                        evaluation["api_status"] = "success"
                        evaluation["evaluator_type"] = "groq"

                        # Cache extracted response too
                        _cache_response(prompt_template, text, cache_model, temperature, matched, confidence, evaluation)

                        return matched, confidence, evaluation
                    except json.JSONDecodeError:
                        pass
                logger.error("[Groq SDK] Failed to parse LLM response as JSON.")
                logger.error(f"[Groq SDK] Content type: {type(content)}, length: {len(content) if content else 0}")
                logger.error(f"[Groq SDK] Raw content: {repr(content[:1000]) if content else 'EMPTY'}")
                return False, 0.0, {"error": "Invalid response format", "raw_content": content}

        except Exception as e:
            error_msg = f"Error in Groq SDK evaluation: {str(e)}"
            logger.error(error_msg)
            import traceback
            logger.error(f"[Groq SDK] Traceback: {traceback.format_exc()}")
            return False, 0.0, {"error": error_msg}

    def _evaluate_with_rest(self, prompt_template: str, text: str, temperature: float) -> Tuple[bool, float, Dict[str, Any]]:
        """Evaluate using REST API (fallback method)."""
        # Ensure temperature is within valid range and not exactly 0 (Groq converts 0 to 1e-8)
        if temperature == 0:
            temperature = 1e-8
        elif temperature > 2.0:
            temperature = 2.0

        # Check cache first after provider-specific normalization.
        cache_model = f"groq:{self.model}:reasoning={self.reasoning_effort}"
        cached = _get_cached_response(prompt_template, text, cache_model, temperature)
        if cached is not None:
            return cached

        try:
            # Format the complete prompt with clear structure for JSON output
            full_prompt = (
                f"## Evaluation Criteria\n{prompt_template}\n\n"
                f"## Text to Evaluate\n{text}\n\n"
                f"## Required Response Format\n"
                f"You MUST respond with ONLY a valid JSON object (no markdown, no explanation):\n"
                f'{{"matched": true/false, "confidence": 0.0-1.0, "reason": "brief explanation"}}'
            )

            # Build request JSON
            request_json = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a security evaluation assistant. Your task is to analyze text against "
                            "specific criteria and determine if it matches.\n\n"
                            "CRITICAL: You MUST respond with ONLY a valid JSON object. No markdown formatting, "
                            "no code blocks, no explanation text - just the raw JSON.\n\n"
                            "Response format: {\"matched\": boolean, \"confidence\": float 0-1, \"reason\": string}"
                        )
                    },
                    {"role": "user", "content": full_prompt}
                ],
                "temperature": temperature,
                "max_completion_tokens": 4096,
                "top_p": 1,
                "response_format": {"type": "json_object"}
            }

            # Add reasoning_effort for compatible models
            if "safeguard" in self.model or "gpt-oss" in self.model:
                request_json["reasoning_effort"] = self.reasoning_effort

            # Call the Groq API using the shared session
            response = self.session.post(
                self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=request_json,
                timeout=60  # Increased timeout for reasoning models
            )

            # Process the response
            if response.status_code == 200:
                result = response.json()

                # Debug: log the full response structure for troubleshooting
                if not result.get("choices"):
                    logger.error(f"Groq API returned no choices. Full response: {result}")
                    return False, 0.0, {"error": "No choices in response", "raw_response": str(result)[:500]}

                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

                # Handle empty content
                if not content or not content.strip():
                    logger.error(f"Groq API returned empty content. Full response: {result}")
                    return False, 0.0, {"error": "Empty content in response", "raw_response": str(result)[:500]}

                # Debug: log raw content before parsing
                logger.debug(f"[Groq REST] Raw LLM content (first 500 chars): {repr(content[:500])}")

                # Parse the JSON response
                try:
                    evaluation = json.loads(content)
                    matched = bool(evaluation.get("matched", False))
                    confidence = max(0.0, min(1.0, float(evaluation.get("confidence", 0.0))))

                    # Add additional info to the result
                    evaluation["model"] = self.model
                    evaluation["api_status"] = "success"
                    evaluation["evaluator_type"] = "groq"
                    evaluation["temperature"] = temperature

                    # Cache the successful response
                    _cache_response(prompt_template, text, cache_model, temperature, matched, confidence, evaluation)

                    return matched, confidence, evaluation
                except json.JSONDecodeError as e:
                    logger.error("[Groq REST] Failed to parse LLM response as JSON.")
                    logger.error(f"[Groq REST] JSON error: {e}")
                    logger.error(f"[Groq REST] Content type: {type(content)}, length: {len(content) if content else 0}")
                    logger.error(f"[Groq REST] Raw content: {repr(content[:1000]) if content else 'EMPTY'}")
                    logger.error(f"[Groq REST] Full API response: {result}")
                    return False, 0.0, {"error": "Invalid JSON format", "raw_content": content[:500]}
            else:
                error_msg = f"[Groq REST] API error: {response.status_code}"
                logger.error(error_msg)
                logger.error(f"[Groq REST] Response body: {response.text[:1000]}")
                return False, 0.0, {"error": error_msg, "status_code": response.status_code}

        except requests.Timeout:
            error_msg = "[Groq REST] API request timed out after 60s"
            logger.error(error_msg)
            return False, 0.0, {"error": error_msg}

        except Exception as e:
            error_msg = f"[Groq REST] Error in LLM evaluation: {str(e)}"
            logger.error(error_msg)
            import traceback
            logger.error(f"[Groq REST] Traceback: {traceback.format_exc()}")
            return False, 0.0, {"error": error_msg}


class AnthropicEvaluator(LLMEvaluator):
    """
    LLM evaluator using Anthropic's Claude API.
    Evaluates prompts using Claude models.
    """
    
    def __init__(self, api_key: Optional[str] = None, model: str = "claude-3-sonnet-20240229"):
        """
        Initialize the Claude LLM evaluator.
        
        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY environment variable)
            model: Anthropic model to use
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self.base_url = "https://api.anthropic.com/v1/messages"
        self.session = _get_shared_session()  # Use shared session for connection reuse
        
        # Validate API key
        if not self.api_key:
            logger.warning("No API key provided for Anthropic LLM evaluator. Set ANTHROPIC_API_KEY environment variable or pass api_key.")
    
    def evaluate(self, pattern: str, text: str) -> Union[bool, Tuple[bool, float]]:
        """
        Basic evaluate implementation for the BaseEvaluator interface.
        
        Args:
            pattern: The pattern to evaluate
            text: The text to check
            
        Returns:
            Boolean indicating match or tuple of (matched, confidence)
        """
        matched, confidence, _ = self.evaluate_prompt(pattern, text)
        return matched, confidence
    
    def evaluate_prompt(self, prompt_template: str, text: str, temperature: float = 0.1) -> Tuple[bool, float, Dict[str, Any]]:
        """
        Evaluate a text using the provided prompt template with Anthropic API.

        Args:
            prompt_template: The prompt to send to the LLM
            text: The text to evaluate
            temperature: Temperature setting for the model (0.0-1.0)

        Returns:
            Tuple of (matched, confidence, details)
        """
        # Input validation - handle None/empty text gracefully
        if text is None or not isinstance(text, str) or not text.strip():
            return False, 0.0, {"error": "Invalid or empty text"}

        if not self.api_key:
            # No API key available
            return False, 0.0, {"error": "No API key available"}

        try:
            # Format the complete prompt
            system_prompt = (
                "You evaluate text based on given criteria. "
                "Respond with a JSON object containing 'matched' (boolean), "
                "'confidence' (float 0-1), and 'reason' (string)."
            )

            user_prompt = (
                f"{prompt_template}\n\n"
                f"Text to evaluate: {text}\n\n"
                f"Respond with a JSON object with keys: matched (boolean), confidence (float 0-1), reason (string)"
            )
            
            # Call the Anthropic API using the shared session
            response = self.session.post(
                self.base_url,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": self.model,
                    "system": system_prompt,
                    "messages": [
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": temperature,  # Use the provided temperature
                    "max_tokens": 200
                },
                timeout=15  # Longer timeout for Anthropic API
            )
            
            # Process the response
            if response.status_code == 200:
                result = response.json()
                content = result.get("content", [{}])[0].get("text", "{}")
                
                # Parse the JSON response
                try:
                    # Find JSON in response (Claude might add text before/after)
                    json_start = content.find('{')
                    json_end = content.rfind('}') + 1
                    
                    if json_start >= 0 and json_end > json_start:
                        json_content = content[json_start:json_end]
                        evaluation = json.loads(json_content)
                        matched = bool(evaluation.get("matched", False))
                        confidence = max(0.0, min(1.0, float(evaluation.get("confidence", 0.0))))
                        
                        # Add additional info to the result
                        evaluation["model"] = self.model
                        evaluation["api_status"] = "success"
                        evaluation["evaluator_type"] = "anthropic"
                        evaluation["temperature"] = temperature  # Include the temperature used
                        
                        return matched, confidence, evaluation
                    else:
                        return False, 0.0, {"error": "No JSON found in response", "raw_content": content}
                except json.JSONDecodeError as e:
                    logger.error("[Anthropic] Failed to parse Claude response as JSON.")
                    logger.error(f"[Anthropic] JSON error: {e}")
                    logger.error(f"[Anthropic] Content type: {type(content)}, length: {len(content) if content else 0}")
                    logger.error(f"[Anthropic] Raw content: {repr(content[:1000]) if content else 'EMPTY'}")
                    return False, 0.0, {"error": "Invalid response format", "raw_content": content}
            else:
                error_msg = f"[Anthropic] API error: {response.status_code}"
                logger.error(error_msg)
                logger.error(f"[Anthropic] Response body: {response.text[:1000]}")
                return False, 0.0, {"error": error_msg, "status_code": response.status_code}

        except requests.Timeout:
            error_msg = "[Anthropic] API request timed out"
            logger.error(error_msg)
            return False, 0.0, {"error": error_msg}

        except Exception as e:
            error_msg = f"[Anthropic] Error in LLM evaluation: {str(e)}"
            logger.error(error_msg)
            import traceback
            logger.error(f"[Anthropic] Traceback: {traceback.format_exc()}")
            return False, 0.0, {"error": error_msg}


class AzureOpenAIEvaluator(OpenAIEvaluator):
    """
    LLM evaluator using Azure OpenAI Service.
    Extends OpenAIEvaluator with Azure-specific configuration.
    """
    
    def __init__(
        self, 
        api_key: Optional[str] = None, 
        endpoint: Optional[str] = None,
        deployment_name: str = "gpt-35-turbo",
        api_version: str = "2023-05-15"
    ):
        """
        Initialize the Azure OpenAI evaluator.
        
        Args:
            api_key: Azure OpenAI API key (defaults to AZURE_OPENAI_API_KEY environment variable)
            endpoint: Azure OpenAI endpoint (defaults to AZURE_OPENAI_ENDPOINT environment variable)
            deployment_name: Azure deployment name
            api_version: Azure OpenAI API version
        """
        # Use Azure-specific environment variables
        self.api_key = api_key or os.environ.get("AZURE_OPENAI_API_KEY")
        self.endpoint = endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT")
        self.deployment_name = deployment_name
        self.api_version = api_version
        self.session = _get_shared_session()  # Use shared session for connection reuse
        
        # Validate configuration
        if not self.api_key:
            logger.warning("No API key provided for Azure OpenAI evaluator. Set AZURE_OPENAI_API_KEY environment variable or pass api_key.")

        if not self.endpoint:
            logger.warning("No endpoint provided for Azure OpenAI evaluator. Set AZURE_OPENAI_ENDPOINT environment variable or pass endpoint.")
        
        # Calculate base URL
        if self.endpoint:
            # Remove trailing slash if present
            endpoint = self.endpoint.rstrip('/')
            self.base_url = f"{endpoint}/openai/deployments/{deployment_name}/chat/completions?api-version={api_version}"
        else:
            self.base_url = None
    
    def evaluate_prompt(self, prompt_template: str, text: str, temperature: float = 0.1) -> Tuple[bool, float, Dict[str, Any]]:
        """
        Evaluate a text using the provided prompt template with Azure OpenAI API.

        Args:
            prompt_template: The prompt to send to the LLM
            text: The text to evaluate
            temperature: Temperature setting for the model (0.0-1.0)

        Returns:
            Tuple of (matched, confidence, details)
        """
        # Input validation - handle None/empty text gracefully
        if text is None or not isinstance(text, str) or not text.strip():
            return False, 0.0, {"error": "Invalid or empty text"}

        if not self.api_key or not self.base_url:
            # Missing configuration
            return False, 0.0, {"error": "Missing Azure OpenAI configuration"}

        try:
            # Format the complete prompt
            full_prompt = (
                f"{prompt_template}\n\n"
                f"Text to evaluate: {text}\n\n"
                f"Respond with a JSON object with keys: matched (boolean), confidence (float 0-1), reason (string)"
            )

            # Call the Azure OpenAI API using the shared session
            response = self.session.post(
                self.base_url,
                headers={
                    "api-key": self.api_key,
                    "Content-Type": "application/json"
                },
                json={
                    "messages": [
                        {
                            "role": "system", 
                            "content": "You are a helpful assistant that evaluates text based on the given criteria. "
                                      "Respond with a JSON object containing 'matched' (boolean), 'confidence' (float 0-1), "
                                      "and 'reason' (string)."
                        },
                        {"role": "user", "content": full_prompt}
                    ],
                    "temperature": temperature,  # Use the provided temperature
                    "response_format": {"type": "json_object"}
                },
                timeout=10
            )
            
            # Process the response (same as OpenAI)
            if response.status_code == 200:
                result = response.json()
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                
                # Parse the JSON response
                try:
                    evaluation = json.loads(content)
                    matched = bool(evaluation.get("matched", False))
                    confidence = max(0.0, min(1.0, float(evaluation.get("confidence", 0.0))))
                    
                    # Add additional info to the result
                    evaluation["model"] = self.deployment_name
                    evaluation["api_status"] = "success"
                    evaluation["evaluator_type"] = "azure"
                    evaluation["temperature"] = temperature  # Include the temperature used
                    
                    return matched, confidence, evaluation
                except json.JSONDecodeError as e:
                    logger.error("[Azure] Failed to parse Azure OpenAI response as JSON.")
                    logger.error(f"[Azure] JSON error: {e}")
                    logger.error(f"[Azure] Content type: {type(content)}, length: {len(content) if content else 0}")
                    logger.error(f"[Azure] Raw content: {repr(content[:1000]) if content else 'EMPTY'}")
                    return False, 0.0, {"error": "Invalid response format", "raw_content": content}
            else:
                error_msg = f"[Azure] API error: {response.status_code}"
                logger.error(error_msg)
                logger.error(f"[Azure] Response body: {response.text[:1000]}")
                return False, 0.0, {"error": error_msg, "status_code": response.status_code}

        except Exception as e:
            error_msg = f"[Azure] Error in Azure OpenAI evaluation: {str(e)}"
            logger.error(error_msg)
            import traceback
            logger.error(f"[Azure] Traceback: {traceback.format_exc()}")
            return False, 0.0, {"error": error_msg}


class OllamaEvaluator(LLMEvaluator):
    """
    LLM evaluator using local Ollama models.
    Evaluates prompts using models run through Ollama API.
    """
    
    def __init__(self, 
                 host: Optional[str] = None,
                 model: str = "llama3",
                 timeout: int = 30,
                 debug: bool = True):
        """
        Initialize the Ollama LLM evaluator.
        
        Args:
            host: Ollama host URL (defaults to OLLAMA_HOST environment variable or http://localhost:11434)
            model: Ollama model to use (defaults to llama3)
            timeout: Timeout in seconds for API calls
            debug: Enable debug output
        """
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self.model = model
        self.timeout = timeout
        self.debug = debug
        self.session = _get_shared_session()  # Use shared session for connection reuse
        
        # Remove trailing slash if present
        self.host = self.host.rstrip('/')
        self.base_url = f"{self.host}/api/chat"
        
        # Validate host
        if not self.host:
            logger.warning("No host provided for Ollama LLM evaluator. Set OLLAMA_HOST environment variable or pass host.")
    
    def evaluate(self, pattern: str, text: str) -> Union[bool, Tuple[bool, float]]:
        """
        Basic evaluate implementation for the BaseEvaluator interface.
        
        Args:
            pattern: The pattern to evaluate
            text: The text to check
            
        Returns:
            Boolean indicating match or tuple of (matched, confidence)
        """
        matched, confidence, _ = self.evaluate_prompt(pattern, text)
        return matched, confidence
    
    def _debug_print(self, message, data=None):
        """Print debug information if debug mode is enabled."""
        if not self.debug:
            return

        logger.debug("[Ollama] %s", message)
        if data is None:
            return

        if isinstance(data, str) and len(data) > 500:
            logger.debug("[Ollama] Data preview: %s...%s", data[:200], data[-200:])
        else:
            logger.debug("[Ollama] Data: %r", data)
    
    def _extract_response_from_streaming_json(self, response_text):
        """
        Extract complete response from streaming JSON format.
        Each line is a separate JSON object with a piece of the final content.
        """
        self._debug_print("Processing streaming response format")
        
        # Split the response into lines
        lines = response_text.strip().split('\n')
        self._debug_print(f"Found {len(lines)} response chunks")
        
        # Collect all content pieces
        full_content = ""
        
        for i, line in enumerate(lines):
            try:
                # Parse each line as a separate JSON object
                chunk = json.loads(line)
                
                # Extract the content from this chunk
                content_piece = chunk.get("message", {}).get("content", "")
                full_content += content_piece
                
                # If this is the last chunk and has done=true, note it
                if chunk.get("done", False) and i == len(lines) - 1:
                    self._debug_print("Found final chunk with done=true")
            except json.JSONDecodeError:
                self._debug_print(f"Failed to parse chunk {i+1} as JSON")
                continue
        
        self._debug_print(f"Reconstructed full content: {full_content}")
        return full_content
    
    def _extract_response_fields(self, content):
        """
        Extract key fields from response content using regex patterns.
        This is used when JSON parsing fails.
        """
        self._debug_print("Attempting to extract fields using regex")
        
        # Try to find matched value from text
        matched_pattern = r'"matched"\s*:\s*(true|false)'
        confidence_pattern = r'"confidence"\s*:\s*([0-9.]+)'
        reason_pattern = r'"reason"\s*:\s*"([^"]*)"'
        
        matched_match = re.search(matched_pattern, content, re.IGNORECASE)
        confidence_match = re.search(confidence_pattern, content)
        reason_match = re.search(reason_pattern, content)
        
        # Set default values
        matched = False
        confidence = 0.5
        reason = "Manually extracted from response"
        
        # Update with extracted values if found
        if matched_match:
            matched = matched_match.group(1).lower() == 'true'
            self._debug_print(f"Found matched = {matched}")
        else:
            # Try to infer from text
            lower_content = content.lower()
            if "yes" in lower_content or "true" in lower_content or "match" in lower_content:
                matched = True
                self._debug_print(f"Inferred matched = {matched}")
        
        if confidence_match:
            try:
                confidence = float(confidence_match.group(1))
                if confidence < 0 or confidence > 1:
                    confidence = max(0, min(confidence, 1))  # Clamp to 0-1 range
                self._debug_print(f"Found confidence = {confidence}")
            except ValueError:
                pass
        
        if reason_match:
            reason = reason_match.group(1)
            self._debug_print(f"Found reason = {reason}")
        
        return {
            "matched": matched,
            "confidence": confidence,
            "reason": reason,
            "evaluator_type": "ollama",
            "extraction_method": "regex",
            "raw_content": content[:100] + ("..." if len(content) > 100 else "")
        }
    
    def evaluate_prompt(self, prompt_template: str, text: str, temperature: float = 0.1) -> Tuple[bool, float, Dict[str, Any]]:
        """
        Evaluate a text using the provided prompt template with Ollama API.

        Args:
            prompt_template: The prompt to send to the LLM
            text: The text to evaluate
            temperature: Temperature setting for the model (0.0-1.0)

        Returns:
            Tuple of (matched, confidence, details)
        """
        # Input validation - handle None/empty text gracefully
        if text is None or not isinstance(text, str) or not text.strip():
            return False, 0.0, {"error": "Invalid or empty text"}

        try:
            # Format the complete prompt
            system_prompt = (
                "You evaluate text based on given criteria. "
                "Respond with ONLY a JSON object containing 'matched' (boolean), "
                "'confidence' (float 0-1), and 'reason' (string). "
                "Format your response as a JSON object and nothing else. "
                "Do not add any explanation before or after the JSON."
            )

            user_prompt = (
                f"{prompt_template}\n\n"
                f"Text to evaluate: {text}\n\n"
                f"IMPORTANT: Respond with ONLY a JSON object with these exact keys: matched (boolean), confidence (float 0-1), reason (string)"
            )
            
            self._debug_print("Sending request to Ollama API")
            
            # Call the Ollama API using the shared session
            response = self.session.post(
                self.base_url,
                headers={"Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "options": {
                        "temperature": temperature  # Use the provided temperature
                    },
                    "stream": False  # Explicitly disable streaming
                },
                timeout=self.timeout
            )
            
            # Process the response
            if response.status_code == 200:
                self._debug_print("Received 200 response from Ollama API")
                
                # First, check if we're dealing with streaming JSON response
                response_text = response.text
                self._debug_print("Raw response text:", response_text)
                
                if '\n' in response_text and response_text.strip().startswith('{"model":'):
                    # This appears to be a streaming response, reconstruct it
                    full_content = self._extract_response_from_streaming_json(response_text)
                    
                    # Try to parse the reconstructed content as JSON
                    try:
                        result_json = json.loads(full_content)
                        self._debug_print("Successfully parsed reconstructed content as JSON")
                        
                        if "matched" in result_json:
                            matched = bool(result_json.get("matched", False))
                            confidence = float(result_json.get("confidence", 0.5))
                            
                            result_json["model"] = self.model
                            result_json["api_status"] = "success"
                            result_json["evaluator_type"] = "ollama"
                            result_json["extraction_method"] = "streaming_reconstruct"
                            result_json["temperature"] = temperature  # Include the temperature used
                            
                            return matched, confidence, result_json
                    except json.JSONDecodeError:
                        self._debug_print("Reconstructed content is not valid JSON, using regex fallback")
                    
                    # If JSON parsing failed, use regex fallback
                    extraction = self._extract_response_fields(full_content)
                    extraction["model"] = self.model
                    extraction["api_status"] = "partial"
                    extraction["temperature"] = temperature  # Include the temperature used
                    
                    return extraction["matched"], extraction["confidence"], extraction
                else:
                    # Not a streaming response, try to parse as regular JSON
                    try:
                        result = json.loads(response_text)
                        content = result.get("message", {}).get("content", "{}")
                        self._debug_print("Content from regular JSON response:", content)
                        
                        try:
                            # Try to parse the content as JSON
                            content_json = json.loads(content)
                            if "matched" in content_json:
                                matched = bool(content_json.get("matched", False))
                                confidence = float(content_json.get("confidence", 0.5))
                                
                                content_json["model"] = self.model
                                content_json["api_status"] = "success"
                                content_json["evaluator_type"] = "ollama"
                                content_json["extraction_method"] = "regular_json"
                                content_json["temperature"] = temperature  # Include the temperature used
                                
                                return matched, confidence, content_json
                        except json.JSONDecodeError:
                            self._debug_print("Content is not valid JSON, using regex fallback")
                        
                        # If JSON parsing failed, use regex fallback
                        extraction = self._extract_response_fields(content)
                        extraction["model"] = self.model
                        extraction["api_status"] = "partial"
                        extraction["temperature"] = temperature  # Include the temperature used
                        
                        return extraction["matched"], extraction["confidence"], extraction
                    except json.JSONDecodeError:
                        self._debug_print("Response is not valid JSON, using regex fallback on raw response")
                        
                        # Direct extraction from raw response
                        extraction = self._extract_response_fields(response_text)
                        extraction["model"] = self.model
                        extraction["api_status"] = "partial"
                        extraction["temperature"] = temperature  # Include the temperature used
                        
                        return extraction["matched"], extraction["confidence"], extraction
            else:
                error_msg = f"API error: {response.status_code}, {response.text}"
                self._debug_print(error_msg)
                logger.error(error_msg)
                return False, 0.0, {"error": error_msg, "status_code": response.status_code, "evaluator_type": "ollama"}

        except requests.Timeout:
            error_msg = "API request timed out"
            self._debug_print(error_msg)
            logger.error(error_msg)
            return False, 0.0, {"error": error_msg, "evaluator_type": "ollama"}

        except Exception as e:
            error_msg = f"Error in Ollama evaluation: {str(e)}"
            self._debug_print(f"Exception: {type(e).__name__} - {str(e)}")
            logger.error(error_msg)
            import traceback
            self._debug_print(f"Traceback: {traceback.format_exc()}")
            logger.debug(f"Traceback: {traceback.format_exc()}")
            return False, 0.0, {"error": error_msg, "evaluator_type": "ollama"}


def get_validated_evaluator(llm_type: str, model: Optional[str] = None, verbose: bool = False) -> Optional[LLMEvaluator]:
    """
    Get a validated LLM evaluator with proper API key checking and no fallback logic.
    If the requested evaluator can't be created, raises an exception.
    
    Args:
        llm_type: Type of LLM evaluator ('openai', 'anthropic', 'azure', 'ollama', 'groq', or 'openrouter')
        model: Optional model name to use
        verbose: Whether to print verbose information
        
    Returns:
        An LLM evaluator instance or raises an exception if it cannot be created
        
    Raises:
        ValueError: If the required API keys or configuration are not available
    """
    # Initialize variables for selected evaluator
    selected_model = None
    
    # Handle the requested evaluator without fallbacks
    if llm_type.lower() == 'anthropic':
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            selected_model = _select_model("anthropic", model, "claude-3-sonnet-20240229")
            if verbose:
                logger.info(f"✓ Using Anthropic evaluator with model: {selected_model}")
            return AnthropicEvaluator(api_key=api_key, model=selected_model)
        else:
            raise ValueError("ANTHROPIC_API_KEY not set in environment variables. Cannot use Anthropic evaluator.")
    
    elif llm_type.lower() == 'azure':
        api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        if api_key and endpoint:
            deployment = _select_model("azure", model, "gpt-35-turbo")
            if verbose:
                logger.info(f"✓ Using Azure OpenAI evaluator with deployment: {deployment}")
            return AzureOpenAIEvaluator(api_key=api_key, endpoint=endpoint, deployment_name=deployment)
        else:
            missing = []
            if not api_key:
                missing.append("AZURE_OPENAI_API_KEY")
            if not endpoint:
                missing.append("AZURE_OPENAI_ENDPOINT")
            raise ValueError(f"Required environment variables not set: {', '.join(missing)}. Cannot use Azure evaluator.")
    
    elif llm_type.lower() == 'ollama':
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        selected_model = _select_model("ollama", model, "llama3")
        try:
            # Try a simple ping to see if Ollama is running
            requests.get(f"{host}/api/tags", timeout=2)
            if verbose:
                logger.info(f"✓ Using Ollama evaluator with model: {selected_model}")
            return OllamaEvaluator(host=host, model=selected_model)
        except (requests.ConnectionError, requests.Timeout):
            raise ValueError(f"Could not connect to Ollama at {host}. Ensure Ollama service is running.")
    
    elif llm_type.lower() == 'groq':
        api_key = os.environ.get("GROQ_API_KEY")
        if api_key:
            selected_model = _select_model("groq", model, "llama-3.3-70b-versatile")
            if verbose:
                logger.info(f"✓ Using Groq evaluator with model: {selected_model}")
            return GroqEvaluator(api_key=api_key, model=selected_model, use_sdk=True)
        else:
            raise ValueError("GROQ_API_KEY not set in environment variables. Cannot use Groq evaluator.")
    
    elif llm_type.lower() == 'openai':
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            selected_model = _select_model("openai", model, "gpt-4o-mini")
            if verbose:
                logger.info(f"✓ Using OpenAI evaluator with model: {selected_model}")
            return OpenAIEvaluator(api_key=api_key, model=selected_model)
        else:
            raise ValueError("OPENAI_API_KEY not set in environment variables. Cannot use OpenAI evaluator.")

    elif llm_type.lower() == 'openrouter':
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if api_key:
            selected_model = _select_model("openrouter", model, "openai/gpt-5.2")
            if verbose:
                logger.info(f"✓ Using OpenRouter evaluator with model: {selected_model}")
            return OpenRouterEvaluator(api_key=api_key, model=selected_model)
        else:
            raise ValueError("OPENROUTER_API_KEY not set in environment variables. Cannot use OpenRouter evaluator.")
    
    else:
        # Invalid LLM type
        raise ValueError(f"Unsupported LLM type: {llm_type}. Supported types are: openai, anthropic, azure, ollama, groq, openrouter")
