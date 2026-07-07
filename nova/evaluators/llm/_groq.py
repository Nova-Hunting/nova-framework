"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia
twitter: @fr0gger_
License: MIT License
Version: see nova._version
Description: Groq Cloud LLM evaluator (SDK and REST modes)
"""

import os
import json
import re
from typing import Dict, Optional, Tuple, Any, Union

import requests

from nova.evaluators.base import LLMEvaluator
from nova.evaluators.llm._shared import (
    _get_shared_session,
    _get_cached_response,
    _cache_response,
    logger,
)


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
