"""Bounded, explicitly activated OpenRouter Decisions HTTP transport."""

import json
import os
import threading
import time
import requests

from nova.core.sys1 import Sys1Batch
from .config import Sys1Config
from .projection import question, record, validate_answer, project


def reject_constant(value):
    raise ValueError("Nonfinite JSON number")


class TransportError(Exception):
    """A safe diagnostic code, never a response body or request state."""


class OpenRouterSys1Evaluator:
    endpoint = "https://openrouter.ai/api/alpha/decisions"

    def __init__(self, config=None, *, api_key=None, session_factory=requests.Session):
        self.config = Sys1Config.resolve(config)
        self._api_key = api_key
        self._session_factory = session_factory
        self._local = threading.local()
        self._semaphore = threading.BoundedSemaphore(self.config.max_concurrency)

    def _key(self):
        if self._api_key is not None:
            return self._api_key
        from nova.utils.config import get_config
        return os.environ.get("OPENROUTER_API_KEY") or get_config().config.get("api_keys", {}).get("openrouter")

    def _request(self, body, key):
        if not hasattr(self._local, "session"):
            self._local.session = self._session_factory()
        for attempt in range(self.config.retries + 1):
            self._local.http_attempts += 1
            try:
                with self._local.session.post(
                    self.endpoint, data=body,
                    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                    timeout=(self.config.connect_timeout_seconds, self.config.timeout_seconds),
                    allow_redirects=False, stream=True,
                ) as response:
                    status = response.status_code
                    if status in (429, 500, 502, 503, 504, 524, 529) and attempt < self.config.retries:
                        delay = response.headers.get("Retry-After", "0.25")
                        try:
                            delay = float(delay)
                        except ValueError:
                            raise TransportError("retry_after_unavailable") from None
                        if not 0 <= delay <= 2:
                            raise TransportError("retry_after_exceeds_limit")
                        time.sleep(delay)
                        continue
                    if status != 200:
                        raise TransportError("authentication" if status in (401, 403) else f"http_{status}")
                    chunks, length = [], 0
                    for chunk in response.iter_content(16384):
                        length += len(chunk)
                        if length > self.config.max_response_bytes:
                            raise TransportError("response_too_large")
                        chunks.append(chunk)
                    try:
                        return json.loads(b"".join(chunks), parse_constant=reject_constant)
                    except (ValueError, UnicodeError):
                        raise TransportError("invalid_response") from None
            except requests.ConnectTimeout:
                if attempt == self.config.retries:
                    raise TransportError("connect_timeout") from None
            except requests.RequestException:
                # Read timeouts and ambiguous connection failures may occur after send.
                raise TransportError("transport_error") from None

    def evaluate_many(self, patterns, state):
        if not patterns:
            return Sys1Batch({})
        mapping = {f"q{i}": name for i, name in enumerate(patterns)}
        evaluations = {name: record(pattern, requested_model=self.config.model, question_id=qid)
                       for qid, name in mapping.items() for pattern in [patterns[name]]}
        metadata = {"requested_model": self.config.model, "request_count": 0}
        try:
            if not self.config.enabled:
                raise TransportError("disabled")
            key = self._key()
            if not key:
                raise TransportError("missing_api_key")
            body = json.dumps({"model": self.config.model, "state": state,
                               "questions": {qid: question(patterns[name]) for qid, name in mapping.items()},
                               "provider": {"allow_fallbacks": False}}, allow_nan=False, ensure_ascii=False).encode("utf-8")
            if len(body) > self.config.max_request_bytes:
                raise TransportError("request_too_large")
            if not self._semaphore.acquire(timeout=self.config.timeout_seconds):
                raise TransportError("concurrency_timeout")
            self._local.http_attempts = 0
            try:
                response = self._request(body, key)
            finally:
                metadata["request_count"] = self._local.http_attempts
                self._semaphore.release()
            if not isinstance(response, dict) or not isinstance(response.get("answers"), dict):
                raise TransportError("invalid_response")
            for key in ("model", "id", "provider", "usage"):
                if key in response:
                    metadata[key] = response[key]
            for qid, name in mapping.items():
                try:
                    answer = validate_answer(patterns[name], response["answers"].get(qid))
                    evaluations[name] = project(patterns[name], answer)
                except (ValueError, TypeError):
                    evaluations[name].status, evaluations[name].reason = "error", "invalid_answer"
                entry = evaluations[name]
                entry.question_id, entry.requested_model = qid, self.config.model
                entry.returned_model, entry.request_id = response.get("model"), response.get("id")
                entry.provider = response.get("provider")
        except TransportError as error:
            for entry in evaluations.values():
                entry.status, entry.reason = "error", str(error)
        except (ValueError, TypeError):
            for entry in evaluations.values():
                entry.status, entry.reason = "error", "invalid_request"
        return Sys1Batch(evaluations, metadata)
