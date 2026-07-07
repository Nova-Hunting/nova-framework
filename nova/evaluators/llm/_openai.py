"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia
twitter: @fr0gger_
License: MIT License
Version: see nova._version
Description: OpenAI-compatible LLM evaluators (OpenAI, OpenRouter, Azure OpenAI)
"""

import os
import json
from typing import Dict, Optional, Tuple, Any, Union

import requests

from nova.evaluators.base import LLMEvaluator
from nova.evaluators.llm._shared import (
    _get_shared_session,
    _get_cached_response,
    _cache_response,
    logger,
)


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

    def _request_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

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
                headers=self._request_headers(),
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

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "openai/gpt-5.2",
        http_referer: Optional[str] = None,
        app_title: Optional[str] = None,
    ):
        """
        Initialize the OpenRouter evaluator with API credentials.

        Args:
            api_key: OpenRouter API key (defaults to OPENROUTER_API_KEY environment variable)
            model: OpenRouter model slug to use
            http_referer: Optional site URL for OpenRouter app attribution
            app_title: Optional app title for OpenRouter app attribution
        """
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self.model = model
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.session = _get_shared_session()
        self.evaluator_type = "openrouter"
        self.log_label = "OpenRouter"
        self.http_referer = http_referer or os.environ.get("OPENROUTER_HTTP_REFERER")
        self.app_title = app_title or os.environ.get("OPENROUTER_APP_TITLE")

        if not self.api_key:
            logger.warning("No API key provided for OpenRouter LLM evaluator. Set OPENROUTER_API_KEY environment variable or pass api_key.")

    def _request_headers(self) -> Dict[str, str]:
        headers = super()._request_headers()
        if self.http_referer:
            headers["HTTP-Referer"] = self.http_referer
        if self.app_title:
            headers["X-OpenRouter-Title"] = self.app_title
        return headers


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
