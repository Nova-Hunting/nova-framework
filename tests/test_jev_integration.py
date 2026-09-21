import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from nova.core.parser import NovaParser
from nova.core.matcher import NovaMatcher
from nova.core.scanner import NovaScanner
from nova.core.jev import JevBatch, NovaEvaluationError
from nova.sdk import Nova, Action
from nova.sdk.decorator import scan, scan_async, protect
from nova.evaluators.jev.projection import validate_answer, project
from nova.evaluators.jev.state import snapshot_state
from test_jev_parser import source


class FixtureEvaluator:
    def __init__(self, confidence=.8, noul=.8, score=2):
        self.calls = []
        self.confidence, self.noul, self.score = confidence, noul, score

    def evaluate_many(self, patterns, state):
        self.calls.append((patterns, state))
        answers = {
            "$scope": {"type": "noul", "noul": self.noul},
            "$operation": {"type": "choice", "choice": "write", "confidence": self.confidence},
            "$risk": {"type": "score", "score": self.score, "confidence": self.confidence},
        }
        return JevBatch({key: project(pattern, validate_answer(pattern, answers[key])) for key, pattern in patterns.items()}, {"model": "fixture"})


def rule(condition="all of jev", extra="", name="Risk"):
    return NovaParser().parse(source(condition, extra=extra, name=name))


@pytest.mark.parametrize("condition,text,expected,calls", [
    ("keywords.$key or jev.$scope", "secret", True, 0),
    ("keywords.$key and jev.$scope", "ordinary", False, 0),
    ("keywords.$key or jev.$scope", "ordinary", True, 1),
    ("jev.$scope", "ordinary", True, 1),
    ("all of jev", "ordinary", True, 1),
])
def test_short_circuit_across_core_scanner_sdk(condition, text, expected, calls):
    r = rule(condition, extra='keywords:\n$key = "secret"\n')
    for kind in ("core", "scanner", "sdk"):
        evaluator = FixtureEvaluator()
        options = {"jev_config": {"enabled": True}, "jev_evaluator": evaluator}
        if kind == "core":
            result = NovaMatcher(r, **options).check_prompt(text)
            matched = result["matched"]
        elif kind == "scanner":
            result = NovaScanner([r], **options).scan_with_details(text)
            matched = result["matched_any"]
            assert "Risk" in result["jev_results"]
        else:
            result = Nova(rules=[r], **options).scan(text)
            matched = bool(result.matches)
            assert "Risk" in result.jev_results
        assert matched is expected
        assert len(evaluator.calls) == calls
        if condition == "all of jev":
            assert len(evaluator.calls[0][0]) == 3


def test_unknown_never_becomes_negative_or_allowed():
    nova = Nova(rules=[rule("not jev.$operation")], jev_config={"enabled": True}, jev_evaluator=FixtureEvaluator(.4))
    with pytest.raises(NovaEvaluationError) as caught:
        nova.scan("synthetic")
    result = caught.value.partial_result
    assert not result.allowed and not result.clean and not result.evaluation_complete
    assert caught.value.causes == ["insufficient_confidence"]
    assert result.jev_results["Risk"]["$operation"]["answer"]["confidence"] == .4


def test_definite_block_survives_another_rule_failure():
    legacy = NovaParser().parse('rule Block {\nkeywords:\n$x = "secret"\ncondition:\n$x\n}')
    nova = Nova(rules=[rule(), legacy], default_action=Action.BLOCK)
    with pytest.raises(NovaEvaluationError) as caught:
        nova.scan("secret")
    assert caught.value.result.blocked
    assert caught.value.result.blocked_rules == ["Block"]
    assert not caught.value.result.allowed
    with pytest.raises(NovaEvaluationError) as caught:
        nova.scan("secret", jev_state={"unsupported": object()})
    assert caught.value.result.blocked
    assert "invalid_state" in caught.value.causes


def test_llm_remains_independent_and_uses_temperature():
    r = rule("jev.$scope and llm.$intent", extra='llm:\n$intent = "Suspicious?"(0.3)\n')
    evaluator = FixtureEvaluator()
    llm = Mock()
    llm.evaluate_prompt.return_value = (True, .9, {})
    matcher = NovaMatcher(r, llm_evaluator=llm, jev_config={"enabled": True}, jev_evaluator=evaluator)
    assert matcher.check_prompt("synthetic")["matched"]
    assert llm.evaluate_prompt.call_args.kwargs == {"temperature": .3}
    with pytest.raises(NovaEvaluationError):
        matcher.check_prompt("synthetic", skip_llm=True)
    assert len(evaluator.calls) == 2


def test_sdk_batches_once_and_keeps_nonmatching_evidence():
    evaluator = FixtureEvaluator(noul=.1)
    nova = Nova(rules=[rule("jev.$scope")], jev_config={"enabled": True}, jev_evaluator=evaluator)
    result = nova.scan("action", skip_llm=True, jev_state={"goal": "test"})
    assert result.clean
    assert result.jev_results["Risk"]["$scope"]["answer"]["noul"] == .1
    assert len(evaluator.calls) == 1
    assert evaluator.calls[0][1] == {"text": "action", "context": {"goal": "test"}}
    assert result.jev_results["Risk"]["$risk"]["status"] == "skipped"
    assert result.to_dict()["evaluation_complete"]


def test_disabled_and_skip_jev_never_call_injected_evaluator(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-key")
    for options, skip in [({}, False), ({"enabled": True}, True)]:
        evaluator = FixtureEvaluator()
        nova = Nova(rules=[rule()], jev_config=options, jev_evaluator=evaluator)
        with pytest.raises(NovaEvaluationError):
            nova.scan("synthetic", skip_jev=skip)
        assert not evaluator.calls


def test_concurrent_scans_have_separate_state_and_evidence():
    evaluator = FixtureEvaluator()
    nova = Nova(rules=[rule()], jev_config={"enabled": True}, jev_evaluator=evaluator)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda i: nova.scan(str(i), jev_state={"id": i}), range(20)))
    assert len(evaluator.calls) == 20
    assert all(state["text"] == str(state["context"]["id"]) for _, state in evaluator.calls)
    assert len({id(result.jev_results) for result in results}) == 20


@pytest.mark.parametrize("async_mode", [False, True])
def test_protection_never_executes_after_unresolved_evaluation(async_mode):
    nova = Nova(rules=[rule()])
    calls = []
    factory = Mock(return_value={"goal": "test"})

    @nova.protect(raise_on_block=False, jev_state_factory=factory)
    def run(prompt):
        calls.append(prompt)

    @nova.protect(raise_on_block=False, jev_state_factory=factory)
    async def run_async(prompt):
        calls.append(prompt)

    with pytest.raises(NovaEvaluationError):
        if async_mode:
            asyncio.run(run_async("synthetic"))
        else:
            run("synthetic")
    assert not calls
    factory.assert_called_once_with({"prompt": "synthetic"})


def test_bound_method_and_standalone_sync_async():
    evaluator = FixtureEvaluator(noul=.1)
    nova = Nova(rules=[rule("jev.$scope")], jev_config={"enabled": True}, jev_evaluator=evaluator)

    class Tool:
        @protect(nova_instance=nova, jev_state_factory=lambda args: {"goal": args["goal"]})
        def run(self, goal, prompt="synthetic"):
            return prompt

    assert Tool().run("test") == "synthetic"
    assert evaluator.calls[-1][1]["context"] == {"goal": "test"}
    assert scan("synthetic", nova_instance=nova).clean
    assert asyncio.run(scan_async("synthetic", nova_instance=nova)).clean


def test_dynamic_rule_uses_shared_configuration():
    evaluator = FixtureEvaluator()
    nova = Nova(jev_config={"enabled": True}, jev_evaluator=evaluator)
    nova.add_rule(rule())
    assert nova.scan("synthetic").match_count == 1
    scanner = NovaScanner(jev_config={"enabled": True}, jev_evaluator=evaluator)
    scanner.add_rule(rule())
    assert scanner.scan("synthetic")


@pytest.mark.parametrize("context", [{1: "value"}, {"number": float("nan")}, {"object": object()}, {"set": {1}}, 42])
def test_invalid_state(context):
    with pytest.raises(ValueError):
        snapshot_state("text", context)


def test_state_snapshot_and_cycle():
    context = {"history": ["before"]}
    state = snapshot_state("action", context)
    context["history"].append("after")
    assert state["context"]["history"] == ["before"]
    context["cycle"] = context
    with pytest.raises(ValueError, match="cycle"):
        snapshot_state("action", context)
