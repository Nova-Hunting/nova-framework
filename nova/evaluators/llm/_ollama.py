"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia
twitter: @fr0gger_
License: MIT License
Version: see nova._version
Description: Local Ollama LLM evaluator
"""

import os
import json
import re
from typing import Dict, Optional, Tuple, Any, Union

import requests

from nova.evaluators.base import LLMEvaluator
from nova.evaluators.llm._shared import _get_shared_session, logger


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
