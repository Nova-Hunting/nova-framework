"""Typed decision through Ollama's System One HTTP API; no Ollama SDK required."""

import os
from urllib.parse import urlsplit

import requests

from .http import HTTPDecisionEvaluator


class OllamaDecisionEvaluator(HTTPDecisionEvaluator):
    provider = "ollama"

    def __init__(self, config=None, *, session_factory=requests.Session):
        super().__init__(config, session_factory=session_factory)
        host = (self.config.host or os.environ.get("OLLAMA_HOST") or "http://localhost:11434").strip()
        if "://" not in host:
            host = "http://" + host
        parsed = urlsplit(host)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or any(char.isspace() for char in host)):
            raise ValueError("Invalid Ollama Decision host; use an HTTP(S) URL without credentials, query or fragment")
        parsed.port  # Validate an explicitly supplied port before any request.
        self.endpoint = host.rstrip("/") + "/v1/systemone"
