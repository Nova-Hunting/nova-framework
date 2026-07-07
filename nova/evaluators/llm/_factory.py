"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia
twitter: @fr0gger_
License: MIT License
Version: see nova._version
Description: Validated LLM evaluator factory
"""

import os
from typing import Optional

import requests

from nova.evaluators.base import LLMEvaluator
from nova.evaluators.llm._shared import _select_model, logger
from nova.evaluators.llm._openai import OpenAIEvaluator, OpenRouterEvaluator, AzureOpenAIEvaluator
from nova.evaluators.llm._anthropic import AnthropicEvaluator
from nova.evaluators.llm._groq import GroqEvaluator
from nova.evaluators.llm._ollama import OllamaEvaluator


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
