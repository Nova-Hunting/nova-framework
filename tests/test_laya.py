"""Offline Laya contract, scheduling and protection tests: no ML runtime required."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import subprocess
import sys
import threading
import time
from unittest.mock import Mock

import pytest

from nova.core.sys1 import NoulPattern, ChoicePattern, ScorePattern, Predicate, NovaEvaluationError
from nova.evaluators.sys1.config import Sys1Config
from nova.evaluators.sys1.factory import create_sys1_evaluator
from nova.evaluators.sys1.laya import LayaSys1Evaluator, preflight
from nova.evaluators.sys1.models import ModelError
from nova.evaluators.sys1.projection import question, validate_answer
from nova.sdk import Nova
from test_sys1_integration import rule


class Tokenizer:
    mask_token = "[MASK]"
    mask_token_id, cls_token_id, sep_token_id = 0, 1, 2
    def __call__(self, text, **kwargs):
        # Count Unicode characters so boundary tests are deterministic.
        return {"input_ids": list(text)}


class Agent:
    def __init__(self):
        self.tok = Tokenizer()
        self.cfg = {"max_len": 1024, "head_max_len": 192}
        self.device = "cpu"
        self.calls = []
        self.response = None
        self.error = None

    def predict(self, state, questions):
        self.calls.append((state, questions))
        if self.error:
            raise self.error
        if self.response is not None:
            return deepcopy(self.response)
        answers = {}
        for qid, q in reversed(list(questions.items())):
            if q["type"] == "noul":
                answers[qid] = {"type": "noul", "noul": .8}
            elif q["type"] == "choice":
                keys = list(q["criteria"])
                answers[qid] = {"type": "choice", "choice": keys[-1], "confidence": .8,
                                "probabilities": {key: float(key == keys[-1]) for key in keys}}
            else:
                size = len(q["criteria"])
                answers[qid] = {"type": "score", "score": size - 1, "confidence": .8,
                                "probabilities": {str(i): float(i == size - 1) for i in range(size)},
                                "legend": {str(i): value for i, value in enumerate(q["criteria"])}}
        return {"model": "laya-rl-agent", "answers": answers, "usage": {"input_tokens": 50, "output_tokens": 0}}


def evaluator(agent=None, **options):
    result = LayaSys1Evaluator(Sys1Config(enabled=True, provider="laya", model="/synthetic/model", **options))
    result._agent = agent or Agent()
    result._expected_device = "cpu"
    result._model_metadata = {"revision": "a" * 40, "checkpoint": "english", "calibration": {"temperature": [1, 1, 1]}}
    return result


def patterns():
    return {"$n": NoulPattern("Truth?", "Yes", "No", .75),
            "$c": ChoicePattern("Category?", {"read": "Read", "write": "Write"}, ("write",), .6),
            "$s": ScorePattern("Impact?", ("None", "Some", "Much"), 1.5, .6)}


def test_mixed_batch_native_answers_and_reuse():
    e = evaluator()
    for _ in range(2):
        batch = e.evaluate_many(patterns(), {"text": "sample", "context": {"goal": "test"}})
        assert all(entry.predicate is Predicate.TRUE for entry in batch.evaluations.values())
        assert batch.metadata["inference_count"] == 1
        assert "request_count" not in batch.metadata
        assert batch.evaluations["$n"].answer.noul == .8
        assert batch.evaluations["$c"].answer.choice == "write"
        assert batch.evaluations["$s"].answer.score == 2
    assert len(e._agent.calls) == 2
    assert all(set(q) == {"type", "instructions", "criteria"} for q in e._agent.calls[0][1].values())
    batch.metadata["calibration"]["temperature"][0] = 99
    assert e._model_metadata["calibration"]["temperature"][0] == 1


@pytest.mark.parametrize("part,reason", [("instructions", "instructions_too_long"), ("criteria", "criteria_too_long"), ("state", "input_too_long")])
def test_preflight_rejects_loss(part, reason):
    agent = Agent()
    q = question(patterns()["$n"])
    state = "sample"
    if part == "instructions":
        q[part] = "word " * 100
    elif part == "criteria":
        q[part]["true"] = "long " * 20
    else:
        state = {"history": ["長" * 1024]}
    with pytest.raises(ModelError, match=reason):
        preflight(agent, state, q)


def test_exact_state_boundary_and_special_tokens():
    agent = Agent()
    q = question(patterns()["$n"])
    used = preflight(agent, "", q)
    preflight(agent, "x" * (1024 - used), q)
    with pytest.raises(ModelError, match="input_too_long"):
        preflight(agent, "x" * (1025 - used), q)
    with pytest.raises(ModelError, match="unsupported_special_token"):
        preflight(agent, "quoted [MASK]", q)


def test_one_invalid_question_does_not_discard_other_evidence():
    e = evaluator()
    r = rule("sys1.$scope or sys1.$operation")
    r.sys1["$operation"] = replace(r.sys1["$operation"], instructions="word " * 100)
    nova = Nova(rules=[r], sys1_config=e.config, sys1_evaluator=e)
    result = nova.scan("sample")
    assert result.matches
    assert result.sys1_results["Risk"]["$operation"]["reason"] == "instructions_too_long"
    assert len(e._agent.calls[0][1]) == 1


@pytest.mark.parametrize("raw", [
    None, {"type": "score", "score": 1}, {"type": "noul", "noul": float("nan")},
    {"type": "noul", "noul": 1.1},
])
def test_invalid_or_missing_answers_are_unknown(raw):
    e = evaluator()
    e._agent.response = {"answers": {"q0": raw}}
    batch = e.evaluate_many({"$n": patterns()["$n"]}, "sample")
    assert batch.evaluations["$n"].predicate is Predicate.UNKNOWN
    assert batch.evaluations["$n"].status == "error"


def test_confidence_is_not_selected_probability_and_missing_is_unknown():
    e = evaluator()
    for confidence in (.4, None):
        e._agent.response = {"answers": {"q0": {"type": "choice", "choice": "write", "confidence": confidence,
                                                 "probabilities": {"read": .01, "write": .99}}}}
        batch = e.evaluate_many({"$c": patterns()["$c"]}, "sample")
        assert batch.evaluations["$c"].predicate is Predicate.UNKNOWN
        assert batch.evaluations["$c"].status == "indeterminate"


def test_provider_precision_and_fractional_score():
    p = patterns()["$s"]
    raw = {"type": "score", "score": 1.5, "probabilities": {"0": 0., "1": .5, "2": .5},
           "legend": {"0": "None", "1": "Some", "2": "Much"}, "confidence": .8}
    assert validate_answer(p, raw, decimal_places=4).score == 1.5
    raw["probabilities"]["0"] = .004
    validate_answer(p, raw)  # Legacy OpenRouter rounding allowance remains intact.
    with pytest.raises(ValueError, match="sum"):
        validate_answer(p, raw, decimal_places=4)


def test_bounds_and_failed_inference_do_not_retry_or_leak():
    e = evaluator(max_batch_questions=1)
    assert e.evaluate_many(patterns(), "sample").evaluations["$n"].reason == "batch_too_large"
    assert not e._agent.calls
    e._agent.error = RuntimeError("private-input-marker")
    batch = e.evaluate_many({"$n": patterns()["$n"]}, "sample")
    assert batch.evaluations["$n"].reason == "inference_failed"
    assert "private-input-marker" not in str(batch)
    assert len(e._agent.calls) == 1


def test_queue_timeout_and_device_change_invalidate_instance():
    e = evaluator(queue_timeout_seconds=.001)
    with e._lock:
        batch = e.evaluate_many(patterns(), "sample")
    assert batch.evaluations["$n"].reason == "queue_timeout"
    agent = e._agent
    original = agent.predict
    def changed(*args):
        response = original(*args)
        agent.device = "cuda:0"
        return response
    agent.predict = changed
    assert e.evaluate_many(patterns(), "sample").evaluations["$n"].reason == "device_changed"
    assert e._agent is None
    assert e.evaluate_many(patterns(), "sample").evaluations["$n"].reason == "device_changed"
    assert len(agent.calls) == 1


def test_failed_fallback_also_invalidates_model():
    e = evaluator()
    agent = e._agent
    def failed(state, questions):
        agent.device = "cuda:0"
        raise RuntimeError("synthetic failure after device change")
    agent.predict = failed
    batch = e.evaluate_many(patterns(), "sample")
    assert batch.evaluations["$n"].reason == "device_changed"
    assert e._agent is None and e._invalidated


@pytest.mark.parametrize("condition,text", [("keywords.$key or sys1.$scope", "secret"), ("keywords.$key and sys1.$scope", "ordinary")])
def test_short_circuit_does_not_load_missing_model(condition, text):
    r = rule(condition, extra='keywords:\n$key = "secret"\n')
    nova = Nova(rules=[r], sys1_config={"enabled": True, "provider": "laya", "model": "/missing"})
    nova._sys1_evaluator._load = Mock(side_effect=AssertionError("must not load"))
    nova.scan(text)
    nova._sys1_evaluator._load.assert_not_called()


@pytest.mark.parametrize("async_mode", [False, True])
def test_required_laya_failure_prevents_protected_call(async_mode):
    nova = Nova(rules=[rule("not sys1.$scope")], sys1_config={"enabled": True, "provider": "laya", "model": "/missing"})
    called = []
    @nova.protect(raise_on_block=False)
    def run(prompt):
        called.append(prompt)
    @nova.protect(raise_on_block=False)
    async def run_async(prompt):
        called.append(prompt)
    with pytest.raises(NovaEvaluationError) as error:
        asyncio.run(run_async("sample")) if async_mode else run("sample")
    assert "model_not_prepared" in error.value.causes
    assert not error.value.result.allowed and not called


def test_concurrent_scans_load_once_and_serialize(monkeypatch):
    e = evaluator()
    agent, e._agent = e._agent, None
    loads = []
    original = e._load
    def load():
        if e._agent is None:
            time.sleep(.01)
            loads.append(1)
            e._agent = agent
        return original()
    monkeypatch.setattr(e, "_load", load)
    active = threading.Lock()
    predict = agent.predict
    def serial(state, questions):
        assert active.acquire(blocking=False)
        try:
            time.sleep(.002)
            return predict(state, questions)
        finally:
            active.release()
    agent.predict = serial
    with ThreadPoolExecutor(max_workers=4) as pool:
        batches = list(pool.map(lambda i: e.evaluate_many(patterns(), {"text": str(i), "id": i}), range(12)))
    assert len(loads) == 1
    assert len(batches) == len(agent.calls) == 12
    assert all(state["text"] == str(state["id"]) for state, _ in agent.calls)


def test_factory_is_lazy_and_laya_extra_is_not_needed_for_help():
    code = """
import sys
from nova.evaluators.sys1.factory import create_sys1_evaluator
e = create_sys1_evaluator({'provider': 'laya', 'model': '/missing'})
assert not any(name in sys.modules for name in ('laya', 'torch', 'transformers'))
"""
    subprocess.run([sys.executable, "-c", code], check=True)
    assert isinstance(create_sys1_evaluator({"provider": "laya", "model": "/missing"}), LayaSys1Evaluator)


def test_provider_selection_cli(monkeypatch, tmp_path, capsys):
    from test_sys1_cli import invoke
    def load(self):
        self._agent = Agent()
        self._expected_device = "cpu"
        return self._agent
    monkeypatch.setattr(LayaSys1Evaluator, "_load", load)
    invoke(monkeypatch, tmp_path, ["--prompt", "sample", "--sys1", "--sys1-provider", "laya", "--sys1-model", "/synthetic", "--verbose"])
    output = capsys.readouterr().out
    assert "Noul $scope: 0.8" in output
    assert "Local inference" in output and "HTTP attempts" not in output


@pytest.mark.parametrize("values", [{"device": "mps"}, {"device": "cuda:-1"}, {"queue_timeout_seconds": 0},
                                    {"max_batch_questions": True}, {"provider": "laya"}])
def test_invalid_laya_config(values):
    with pytest.raises(ValueError):
        Sys1Config(**values)


def test_core_scanner_sdk_and_dynamic_rules_use_same_factory(monkeypatch):
    from nova.core.matcher import NovaMatcher
    from nova.core.scanner import NovaScanner
    def load(self):
        if self._agent is None:
            self._agent = Agent()
            self._expected_device = "cpu"
        return self._agent
    monkeypatch.setattr(LayaSys1Evaluator, "_load", load)
    options = {"enabled": True, "provider": "laya", "model": "/synthetic"}
    r = rule("sys1.$scope")
    matcher = NovaMatcher(None, sys1_config=options)
    matcher.set_rule(r)
    assert matcher.check_prompt("sample")["matched"]
    scanner = NovaScanner(sys1_config=options)
    scanner.add_rule(r)
    assert scanner.scan("sample")
    nova = Nova(sys1_config=options)
    nova.add_rule(r)
    assert asyncio.run(nova.scan_async("sample", skip_llm=True)).matches
    assert nova._matchers[r.name].sys1_evaluator is nova._sys1_evaluator


def test_laya_config_precedence(monkeypatch, tmp_path):
    from nova.utils.config import NovaConfig
    path = tmp_path / "nova.ini"
    path.write_text('[sys1]\nenabled = true\nprovider = laya\nmodel = /prepared\ndevice = cpu\nqueue_timeout_seconds = 1\n')
    config = NovaConfig(str(path))
    monkeypatch.setenv("NOVA_SYS1_DEVICE", "cuda:1")
    monkeypatch.setenv("NOVA_SYS1_MAX_BATCH_QUESTIONS", "12")
    resolved = Sys1Config.resolve({"device": "cpu"}, config)
    assert resolved.provider == "laya" and resolved.model == "/prepared"
    assert resolved.device == "cpu" and resolved.queue_timeout_seconds == 1
    assert resolved.max_batch_questions == 12
