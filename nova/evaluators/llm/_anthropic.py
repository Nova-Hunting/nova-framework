"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia
twitter: @fr0gger_
License: MIT License
Version: see nova._version
Description: Anthropic Claude LLM evaluator
"""

import os
import json
from typing import Dict, Optional, Tuple, Any, Union

import requests

from nova.evaluators.base import LLMEvaluator
from nova.evaluators.llm._shared import _get_shared_session, logger


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
