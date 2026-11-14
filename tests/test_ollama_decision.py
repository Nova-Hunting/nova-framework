"""Ollama System One contract and fail-closed integration, without a running server."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from importlib.metadata import entry_points, requires
from unittest.mock import Mock

import pytest
import requests

from nova.core.decision import NovaEvaluationError, Predicate
from nova.evaluators.decision.config import DecisionConfig
from nova.evaluators.decision.factory import create_decision_evaluator
from nova.evaluators.decision.ollama import OllamaDecisionEvaluator
from nova.sdk import Nova
from nova.utils.config import NovaConfig
from test_decision_cli import invoke
from test_decision_evaluator import NOUL, CHOICE, SCORE, response
from test_decision_integration import rule


def evaluator(responses, **config):
    session = Mock()
    session.post.side_effect = responses
    return OllamaDecisionEvaluator(
        DecisionConfig(enabled=True, provider="ollama", model="laya", **config),
        session_factory=lambda: session,
    ), session


def test_mixed_systemone_request_and_native_results(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "must-not-be-sent")
    ev, session = evaluator([response({"model": "laya", "answers": {
        "q0": {"type": "noul", "noul": .9},
        "q1": {"type": "choice", "choice": "write", "confidence": .8,
               "probabilities": {"read": .1, "write": .9}},
        "q2": {"type": "score", "score": 2.5, "confidence": .8,
               "probabilities": {"0": 0, "1": 0, "2": .5, "3": .5}},
    }, "usage": {"input_tokens": 174, "output_tokens": 1}})], host="http://localhost:11434/")
    state = {"text": "synthetic", "context": {"approved_task": "Read"}}
    batch = ev.evaluate_many({"$n": NOUL, "$c": CHOICE, "$s": SCORE}, state)
    assert all(entry.predicate is Predicate.TRUE for entry in batch.evaluations.values())
    assert batch.evaluations["$s"].answer.score == 2.5
    assert batch.metadata == {"requested_model": "laya", "request_count": 1,
                              "provider": "ollama", "model": "laya",
                              "usage": {"input_tokens": 174, "output_tokens": 1}}
    assert all(entry.provider == "ollama" for entry in batch.evaluations.values())
    assert session.post.call_args.args == ("http://localhost:11434/v1/systemone",)
    kwargs = session.post.call_args.kwargs
    body = json.loads(kwargs["data"])
    assert set(body) == {"model", "state", "questions"}
    assert body["model"] == "laya" and body["state"] == state
    assert list(body["questions"]) == ["q0", "q1", "q2"]
    assert body["questions"]["q0"] == {"type": "noul", "instructions": "Outside?",
                                       "criteria": {"true": "Yes", "false": "No"}}
    assert "threshold" not in body["questions"]["q2"]
    assert kwargs["headers"] == {"Content-Type": "application/json"}
    assert kwargs["timeout"] == (3, 15) and not kwargs["allow_redirects"]


@pytest.mark.parametrize("raw,reason", [
    ({"answers": {}}, "invalid_answer"),
    ({"answers": {"q0": {"type": "noul", "noul": float("nan")}}}, "invalid_response"),
    ({"answers": {"q0": {"type": "refusal"}}}, "invalid_answer"),
    ({"answers": []}, "invalid_response"),
])
def test_invalid_or_refused_answers_remain_unknown(raw, reason):
    ev, _ = evaluator([response(raw)])
    entry = ev.evaluate_many({"$n": NOUL}, "synthetic").evaluations["$n"]
    assert entry.predicate is Predicate.UNKNOWN and entry.reason == reason


def test_missing_answer_keeps_valid_sibling_and_low_confidence():
    ev, _ = evaluator([response({"answers": {
        "q0": {"type": "noul", "noul": .9},
        "q1": {"type": "choice", "choice": "write", "confidence": .1},
    }})])
    entries = ev.evaluate_many({"$n": NOUL, "$c": CHOICE, "$s": SCORE}, "sample").evaluations
    assert entries["$n"].predicate is Predicate.TRUE
    assert entries["$c"].predicate is Predicate.UNKNOWN and entries["$c"].reason == "insufficient_confidence"
    assert entries["$s"].predicate is Predicate.UNKNOWN


@pytest.mark.parametrize("failure,reason", [
    (response({}, 404), "http_404"),
    (response({}, 400), "http_400"),
    (requests.ConnectionError("sensitive server details"), "transport_error"),
    (requests.ReadTimeout("sensitive state"), "transport_error"),
])
def test_failed_required_check_never_allows_negation(failure, reason):
    ev, session = evaluator([failure])
    nova = Nova(rules=[rule("not llm.$scope")], decision_config=ev.config, decision_evaluator=ev)
    with pytest.raises(NovaEvaluationError) as caught:
        nova.scan("synthetic")
    assert not caught.value.result.allowed and not caught.value.result.clean
    assert reason in caught.value.causes
    assert "sensitive" not in str(caught.value.result.to_dict())
    assert session.post.call_count == 1


def test_disabled_and_oversized_requests_do_not_send():
    session = Mock()
    ev = OllamaDecisionEvaluator({"provider": "ollama", "model": "nimble"}, session_factory=lambda: session)
    assert ev.evaluate_many({"$n": NOUL}, "sample").evaluations["$n"].reason == "disabled"
    session.post.assert_not_called()
    ev, session = evaluator([], max_request_bytes=10)
    assert ev.evaluate_many({"$n": NOUL}, "sample").evaluations["$n"].reason == "request_too_large"
    session.post.assert_not_called()
    ev, _ = evaluator([response({"answers": {}})], max_response_bytes=5)
    assert ev.evaluate_many({"$n": NOUL}, "sample").evaluations["$n"].reason == "response_too_large"


def test_host_precedence_and_factory(monkeypatch, tmp_path):
    monkeypatch.delenv("NOVA_DECISION_HOST", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11435")
    assert create_decision_evaluator({"provider": "ollama", "model": "nimble"}).endpoint == "http://127.0.0.1:11435/v1/systemone"
    path = tmp_path / "nova.ini"
    path.write_text('[decision]\nprovider = ollama\nmodel = nimble\nhost = http://file:11434\n')
    config = NovaConfig(str(path))
    assert DecisionConfig.resolve(config=config).host == "http://file:11434"
    monkeypatch.setenv("NOVA_DECISION_HOST", "http://environment:11434")
    assert DecisionConfig.resolve(config=config).host == "http://environment:11434"
    options = DecisionConfig.resolve({"host": "http://explicit:11434/"}, config=config)
    assert create_decision_evaluator(options).endpoint == "http://explicit:11434/v1/systemone"


@pytest.mark.parametrize("host", ["ftp://localhost", "http://", "http://user:secret@localhost", "http://localhost?key=secret", "http://localhost#fragment", "http://localhost:bad", "http://bad host"])
def test_invalid_host_rejected(host):
    with pytest.raises(ValueError):
        create_decision_evaluator({"provider": "ollama", "model": "nimble", "host": host})


@pytest.mark.parametrize("options", [
    {"provider": "laya", "model": "laya"}, {"provider": "ollama"},
    {"device": "cpu"}, {"queue_timeout_seconds": 5}, {"max_batch_questions": 32},
])
def test_removed_runtime_settings_and_missing_ollama_model_rejected(options):
    with pytest.raises(ValueError):
        DecisionConfig.resolve(options)


def test_cli_selects_ollama_host_model_and_results(monkeypatch, tmp_path, capsys):
    def request(self, body, headers):
        assert self.endpoint == "http://localhost:11435/v1/systemone"
        assert self.config.model == "laya" and self.config.provider == "ollama"
        assert set(json.loads(body)) == {"model", "state", "questions"}
        assert "Authorization" not in headers
        return {"model": "laya", "answers": {"q0": {"type": "noul", "noul": .8}}}
    monkeypatch.setattr(OllamaDecisionEvaluator, "_request", request)
    invoke(monkeypatch, tmp_path, ["--prompt", "Hello World", "--decision", "--decision-provider", "ollama", "--decision-model", "laya",
                                   "--decision-host", "http://localhost:11435", "--json", "--verbose"])
    output = json.loads(capsys.readouterr().out)
    assert output["decision_config"]["provider"] == "ollama"
    assert output["decision_results"]["Risk"]["$scope"]["answer"]["noul"] == .8


def test_no_local_runtime_extra_or_setup_command():
    assert not any('extra == "laya"' in item or item.startswith("laya") for item in requires("nova-hunting"))
    assert not any(ep.name == "nova-decision" for ep in entry_points(group="console_scripts"))


@pytest.mark.parametrize("async_mode", [False, True])
def test_protection_stops_on_unavailable_ollama(async_mode):
    ev, _ = evaluator([requests.ConnectionError("offline")])
    nova = Nova(rules=[rule("not llm.$scope")], decision_config=ev.config, decision_evaluator=ev)
    executed = []
    if async_mode:
        @nova.protect(raise_on_block=False)
        async def tool(prompt):
            executed.append(prompt)
    else:
        @nova.protect(raise_on_block=False)
        def tool(prompt):
            executed.append(prompt)
    with pytest.raises(NovaEvaluationError):
        if async_mode:
            asyncio.run(tool("synthetic"))
        else:
            tool("synthetic")
    assert not executed


def test_parallel_batches_keep_request_state_and_counts_separate():
    def post(url, **kwargs):
        body = json.loads(kwargs["data"])
        return response({"model": "nimble", "answers": {
            "q0": {"type": "noul", "noul": .9 if body["state"] == "greeting" else .1},
        }})
    def session_factory():
        return Mock(post=post)
    ev = OllamaDecisionEvaluator({"enabled": True, "provider": "ollama", "model": "nimble"},
                                  session_factory=session_factory)
    states = ["greeting", "ordinary"] * 4
    with ThreadPoolExecutor(max_workers=4) as pool:
        batches = list(pool.map(lambda state: ev.evaluate_many({"$n": NOUL}, state), states))
    assert [batch.evaluations["$n"].predicate for batch in batches] == [
        Predicate.TRUE if state == "greeting" else Predicate.FALSE for state in states
    ]
    assert all(batch.metadata["request_count"] == 1 for batch in batches)
