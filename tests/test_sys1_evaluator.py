import json
from unittest.mock import Mock

import pytest
import requests

from nova.core.sys1 import NoulPattern, ChoicePattern, ScorePattern, Predicate
from nova.evaluators.sys1.config import Sys1Config
from nova.evaluators.sys1.openrouter import OpenRouterSys1Evaluator
from nova.evaluators.sys1.projection import validate_answer, project

NOUL = NoulPattern("Outside?", "Yes", "No", .7)
CHOICE = ChoicePattern("Operation?", {"read": "Read", "write": "Write"}, ("write",), .6)
SCORE = ScorePattern("Impact?", ("None", "Limited", "Serious", "Severe"), 2, .6)


@pytest.mark.parametrize("pattern,answer,expected", [
    (NOUL, {"type": "noul", "noul": .69}, Predicate.FALSE),
    (NOUL, {"type": "noul", "noul": .7}, Predicate.TRUE),
    (CHOICE, {"type": "choice", "choice": "write", "confidence": .6}, Predicate.TRUE),
    (CHOICE, {"type": "choice", "choice": "read", "confidence": .6}, Predicate.FALSE),
    (CHOICE, {"type": "choice", "choice": "write", "confidence": .59}, Predicate.UNKNOWN),
    (CHOICE, {"type": "choice", "choice": "write"}, Predicate.UNKNOWN),
    (SCORE, {"type": "score", "score": 1.99, "confidence": .6}, Predicate.FALSE),
    (SCORE, {"type": "score", "score": 2, "confidence": .6}, Predicate.TRUE),
])
def test_projection(pattern, answer, expected):
    assert project(pattern, validate_answer(pattern, answer)).predicate is expected


@pytest.mark.parametrize("pattern,answer", [
    (NOUL, {}), (NOUL, {"type": "choice", "choice": "yes"}),
    (NOUL, {"type": "noul", "noul": float("nan")}),
    (NOUL, {"type": "noul", "noul": float("inf")}),
    (NOUL, {"type": "noul", "noul": True}),
    (CHOICE, {"type": "choice", "choice": "other"}),
    (CHOICE, {"type": "choice", "choice": "write", "probabilities": {"write": 1}}),
    (CHOICE, {"type": "choice", "choice": "write", "probabilities": {"write": .2, "read": .2}}),
    (SCORE, {"type": "score", "score": 4}),
    (SCORE, {"type": "score", "score": 2, "legend": {"0": "None"}}),
    (SCORE, {"type": "score", "score": 2, "probabilities": {"0": 1, "1": 0, "2": 0, "3": 0}}),
])
def test_invalid_answers(pattern, answer):
    with pytest.raises(ValueError):
        validate_answer(pattern, answer)


def response(payload, status=200, headers=None):
    result = Mock(status_code=status, headers=headers or {})
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    result.iter_content.return_value = [json.dumps(payload).encode()]
    return result


def evaluator(responses, **config):
    session = Mock()
    session.post.side_effect = responses
    return OpenRouterSys1Evaluator(Sys1Config(enabled=True, **config), api_key="synthetic-key", session_factory=lambda: session), session


def test_mixed_batch_mapping_and_local_settings():
    ev, session = evaluator([response({"answers": {
        "q2": {"type": "score", "score": 2.5, "confidence": .8},
        "q0": {"type": "noul", "noul": .8},
        "q1": {"type": "choice", "choice": "write", "confidence": .7}},
        "model": "returned-model", "id": "request-id", "usage": {"cost": .01}})])
    batch = ev.evaluate_many({"$n": NOUL, "$c": CHOICE, "$s": SCORE}, {"text": "synthetic"})
    assert all(entry.predicate is Predicate.TRUE for entry in batch.evaluations.values())
    assert batch.metadata["usage"]["cost"] == .01
    assert batch.evaluations["$s"].answer.score == 2.5
    assert session.post.call_count == 1
    kwargs = session.post.call_args.kwargs
    body = json.loads(kwargs["data"])
    assert set(body["questions"]["q0"]) == {"type", "instructions", "criteria"}
    assert body["provider"] == {"allow_fallbacks": False}
    assert kwargs["timeout"] == (3, 15)
    assert not kwargs["allow_redirects"]


@pytest.mark.parametrize("failure,expected,calls", [
    (response({}, 401), "authentication", 1),
    (response({}, 429, {"Retry-After": "0"}), None, 2),
    (requests.ReadTimeout("secret must not be included"), "transport_error", 1),
    (requests.ConnectTimeout(), None, 2),
])
def test_bounded_retries(failure, expected, calls):
    ev, session = evaluator([failure, response({"answers": {"q0": {"type": "noul", "noul": .8}}})])
    entry = ev.evaluate_many({"$n": NOUL}, "synthetic").evaluations["$n"]
    assert entry.reason == expected
    assert session.post.call_count == calls


def test_explicit_activation_and_limits(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-key")
    session = Mock()
    ev = OpenRouterSys1Evaluator(Sys1Config(), session_factory=lambda: session)
    assert ev.evaluate_many({"$n": NOUL}, "synthetic").evaluations["$n"].reason == "disabled"
    session.post.assert_not_called()
    ev, session = evaluator([], max_request_bytes=10)
    assert ev.evaluate_many({"$n": NOUL}, "synthetic").evaluations["$n"].reason == "request_too_large"
    session.post.assert_not_called()


def test_optional_metadata_absence_and_probability_rounding():
    pattern = ScorePattern("Impact", ("Low", "Medium", "High"), 1)
    answer = validate_answer(pattern, {"type": "score", "score": 1, "probabilities": {"0": .33, "1": .33, "2": .33}})
    assert answer.confidence is None and answer.legend is None
    assert project(pattern, answer).predicate is Predicate.TRUE


def test_missing_answer_does_not_erase_valid_sibling_and_cost_count():
    ev, session = evaluator([response({"answers": {"q0": {"type": "noul", "noul": .9}}})])
    result = ev.evaluate_many({"$n": NOUL, "$s": SCORE}, "synthetic")
    assert result.evaluations["$n"].predicate is Predicate.TRUE
    assert result.evaluations["$s"].reason == "invalid_answer"
    assert result.metadata["request_count"] == session.post.call_count == 1


def test_response_size_and_retry_after_limit():
    ev, session = evaluator([response({"answers": {"q0": {"type": "noul", "noul": .9}}})], max_response_bytes=5)
    assert ev.evaluate_many({"$n": NOUL}, "synthetic").evaluations["$n"].reason == "response_too_large"
    ev, session = evaluator([response({}, 429, {"Retry-After": "100"})])
    assert ev.evaluate_many({"$n": NOUL}, "synthetic").evaluations["$n"].reason == "retry_after_exceeds_limit"
    assert session.post.call_count == 1


def test_selected_choice_not_combined_match_probability():
    pattern = ChoicePattern("Operation?", {"read": "Read", "write": "Write", "delete": "Delete"}, ("write", "delete"))
    raw = {"type": "choice", "choice": "read", "probabilities": {"read": .4, "write": .3, "delete": .3}, "confidence": .01}
    assert project(pattern, validate_answer(pattern, raw)).predicate is Predicate.FALSE
