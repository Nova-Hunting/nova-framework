"""Optional in-process Laya inference with explicit local assets and no truncation."""

from importlib.metadata import PackageNotFoundError, version
from copy import deepcopy
import json
import threading
import time

from nova.core.sys1 import Sys1Batch
from .config import Sys1Config
from .models import LAYA_VERSION, ModelError, validate_model
from .projection import question, record, validate_answer, project


def preflight(agent, state, definition):
    """Reject every slice that would lose tokens in Laya 0.3.5 build_sequence.

    The runtime version is pinned and parity-tested against upstream. Token counts
    include option markers, question prefix, separators and the complete state.
    """
    tok = agent.tok
    kind, criteria = definition["type"], definition["criteria"]
    if kind == "choice":
        options = [f"{key}: {value}" for key, value in criteria.items()]
    elif kind == "score":
        options = [f"level {i}: {value}" for i, value in enumerate(criteria)]
    else:
        options = ["false: " + criteria["false"], "true: " + criteria["true"]]
    text = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False, allow_nan=False)
    # Upstream replaces mask-token text with spaces. Do not silently remove it.
    if not tok.mask_token or any(tok.mask_token in part for part in [text, definition["instructions"], *options]):
        raise ModelError("unsupported_special_token")

    def size(text):
        return len(tok(text, add_special_tokens=False)["input_ids"])

    option_sizes = [1 + size(" " + option) for option in options]
    if any(length > 49 for length in option_sizes):
        raise ModelError("criteria_too_long")
    head_limit = agent.cfg.get("head_max_len", 192)
    budget = head_limit - sum(option_sizes)
    if budget < 16:
        per = max(4, (head_limit - 16) // len(option_sizes))
        if any(length > per for length in option_sizes):
            raise ModelError("criteria_too_long")
    head_size = size(f"{kind} question: {definition['instructions']}")
    if head_size > max(8, budget):
        raise ModelError("instructions_too_long")
    total = head_size + sum(option_sizes) + size(text) + 4
    if total > agent.cfg.get("max_len", 512):
        raise ModelError("input_too_long")
    return total


class LayaSys1Evaluator:
    """One lazily loaded checkpoint per detector; serialization includes loading."""

    def __init__(self, config=None):
        self.config = Sys1Config.resolve(config)
        if self.config.provider != "laya":
            raise ValueError("Laya evaluator requires provider=laya")
        self._lock = threading.Lock()
        self._agent = None
        self._model_metadata = {}
        self._invalidated = False

    def _load(self):
        if self._invalidated:
            raise ModelError("device_changed")
        if self._agent is not None:
            return self._agent
        root, manifest = validate_model(self.config.model)
        try:
            if version("laya") != LAYA_VERSION:
                raise ModelError("unsupported_laya_version")
            import torch
            import laya
        except (ImportError, PackageNotFoundError):
            raise ModelError("missing_laya_dependency") from None
        requested = torch.device(self.config.device)
        if requested.type == "cuda":
            if not torch.cuda.is_available():
                raise ModelError("device_unavailable")
            index = requested.index if requested.index is not None else torch.cuda.current_device()
            if index >= torch.cuda.device_count():
                raise ModelError("device_unavailable")
            requested = torch.device(f"cuda:{index}")
        started = time.perf_counter()
        try:
            agent = laya.load(str(root), device=str(requested))
        except (ImportError, ModuleNotFoundError):
            raise ModelError("missing_laya_dependency") from None
        except Exception:
            raise ModelError("model_load_failed") from None
        if str(agent.device) != str(requested):
            self._invalidated = True
            raise ModelError("device_changed")
        self._expected_device = str(requested)
        self._model_metadata = {
            "repo": manifest["repo"], "checkpoint": manifest["checkpoint"],
            "revision": manifest["revision"], "laya_version": LAYA_VERSION,
            "device": str(agent.device), "load_ms": (time.perf_counter() - started) * 1000,
            "calibration": {"temperature": agent.temperature,
                            "temperature_by_options": agent.temperature_by_options},
        }
        if agent.temperature != agent.temperature_raw or agent.temperature_by_options != agent.temperature_by_options_raw:
            self._model_metadata["warnings"] = ["checkpoint_temperatures_adjusted_by_laya"]
        self._agent = agent
        return agent

    def _device_unchanged(self, agent):
        if str(agent.device) != self._expected_device:
            self._agent, self._invalidated = None, True
            raise ModelError("device_changed")

    def evaluate_many(self, patterns, state):
        mapping = {f"q{i}": name for i, name in enumerate(patterns)}
        evaluations = {name: record(patterns[name], question_id=qid, requested_model=self.config.model, provider="laya")
                       for qid, name in mapping.items()}
        metadata = {"provider": "laya", "requested_model": self.config.model, "inference_count": 0}
        if not patterns:
            return Sys1Batch(evaluations, metadata)
        acquired = False
        try:
            if not self.config.enabled:
                raise ModelError("disabled")
            if len(patterns) > self.config.max_batch_questions:
                raise ModelError("batch_too_large")
            definitions = {qid: question(patterns[name]) for qid, name in mapping.items()}
            body = json.dumps({"state": state, "questions": definitions}, allow_nan=False, ensure_ascii=False)
            if len(body.encode("utf-8")) > self.config.max_request_bytes:
                raise ModelError("request_too_large")
            state = json.loads(body)["state"]  # Isolate direct callers' mutable state too.
            if type(state) not in (str, dict, list):
                raise ModelError("invalid_state")
            acquired = self._lock.acquire(timeout=self.config.queue_timeout_seconds)
            if not acquired:
                raise ModelError("queue_timeout")
            was_loaded = self._agent is not None
            agent = self._load()
            metadata.update(deepcopy(self._model_metadata))
            if was_loaded:
                metadata["load_ms"] = 0
            self._device_unchanged(agent)
            applicable = {}
            for qid, definition in definitions.items():
                try:
                    preflight(agent, state, definition)
                    applicable[qid] = definition
                except ModelError as error:
                    entry = evaluations[mapping[qid]]
                    entry.status, entry.reason = "error", str(error)
            if applicable:
                started = time.perf_counter()
                metadata["inference_count"] = 1
                try:
                    response = agent.predict(state, applicable)
                except MemoryError:
                    raise ModelError("resource_exhausted") from None
                except Exception as error:
                    # Do not expose exception text, which may contain input.
                    code = "resource_exhausted" if "OutOfMemory" in type(error).__name__ else "inference_failed"
                    raise ModelError(code) from None
                finally:
                    metadata["inference_ms"] = (time.perf_counter() - started) * 1000
                    metadata["device"] = str(agent.device)
                    self._device_unchanged(agent)
                if not isinstance(response, dict) or not isinstance(response.get("answers"), dict):
                    raise ModelError("invalid_response")
                if len(json.dumps(response, allow_nan=False).encode("utf-8")) > self.config.max_response_bytes:
                    raise ModelError("response_too_large")
                if set(response["answers"]) - set(applicable):
                    raise ModelError("invalid_response")
                if isinstance(response.get("model"), str):
                    metadata["model"] = response["model"]
                usage = response.get("usage")
                if isinstance(usage, dict):
                    metadata["usage"] = {key: value for key, value in usage.items()
                                         if key in ("input_tokens", "output_tokens") and type(value) is int and value >= 0}
                for qid in applicable:
                    name = mapping[qid]
                    raw = response["answers"].get(qid)
                    try:
                        # Laya's contract supplies these, unlike optional OpenRouter fields.
                        if not isinstance(raw, dict) or (raw.get("type") != "noul" and
                                (raw.get("probabilities") is None or (raw.get("type") == "score" and raw.get("legend") is None))):
                            raise ValueError("Missing answer data")
                        answer = validate_answer(patterns[name], raw, decimal_places=4)
                        entry = project(patterns[name], answer)
                        entry.question_id, entry.requested_model = qid, self.config.model
                        entry.provider, entry.returned_model = "laya", metadata.get("model")
                        evaluations[name] = entry
                    except (ValueError, TypeError, KeyError):
                        evaluations[name].status, evaluations[name].reason = "error", "invalid_answer"
        except ModelError as error:
            for entry in evaluations.values():
                if entry.status == "pending":
                    entry.status, entry.reason = "error", str(error)
        except (ValueError, TypeError, RecursionError, UnicodeError):
            for entry in evaluations.values():
                if entry.status == "pending":
                    entry.status, entry.reason = "error", "invalid_payload"
        except Exception:
            for entry in evaluations.values():
                if entry.status == "pending":
                    entry.status, entry.reason = "error", "laya_unavailable"
        finally:
            if acquired:
                self._lock.release()
        return Sys1Batch(evaluations, metadata)
