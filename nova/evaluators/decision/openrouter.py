"""OpenRouter Decisions adapter with explicit activation and provider fallback disabled."""

import os
import requests

from .http import HTTPDecisionEvaluator, TransportError


class OpenRouterDecisionEvaluator(HTTPDecisionEvaluator):
    endpoint = "https://openrouter.ai/api/alpha/decisions"

    def __init__(self, config=None, *, api_key=None, session_factory=requests.Session):
        super().__init__(config, session_factory=session_factory)
        self._api_key = api_key

    def _headers(self):
        from nova.utils.config import get_config
        key = self._api_key
        if key is None:
            key = os.environ.get("OPENROUTER_API_KEY") or get_config().config.get("api_keys", {}).get("openrouter")
        if not key:
            raise TransportError("missing_api_key")
        return {**super()._headers(), "Authorization": "Bearer " + key}

    def _payload(self, questions, state):
        return {**super()._payload(questions, state), "provider": {"allow_fallbacks": False}}
