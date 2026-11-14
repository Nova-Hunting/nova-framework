import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from nova.core.parser import NovaParser
from nova.core.matcher import NovaMatcher
from nova.core.scanner import NovaScanner
from nova.core.decision import DecisionBatch, NovaEvaluationError
from nova.sdk import Nova, Action
from nova.sdk.decorator import scan, scan_async, protect
from nova.evaluators.decision.projection import validate_answer, project
from nova.evaluators.decision.state import snapshot_state
from test_decision_parser import source


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
        return DecisionBatch({key: project(pattern, validate_answer(pattern, answers[key])) for key, pattern in patterns.items()}, {"model": "fixture"})


def rule(condition="all of llm", extra="", name="Risk"):
    return NovaParser().parse(source(condition, extra=extra, name=name))


@pytest.mark.parametrize("condition,text,expected,calls", [
    ("keywords.$key or llm.$scope", "secret", True, 0),
    ("keywords.$key and llm.$scope", "ordinary", False, 0),
    ("keywords.$key or llm.$scope", "ordinary", True, 1),
    ("llm.$scope", "ordinary", True, 1),
    ("all of llm", "ordinary", True, 1),
])
def test_short_circuit_across_core_scanner_sdk(condition, text, expected, calls):
    r = rule(condition, extra='keywords:\n$key = "secret"\n')
    for kind in ("core", "scanner", "sdk"):
        evaluator = FixtureEvaluator()
        options = {"decision_config": {"enabled": True}, "decision_evaluator": evaluator}
        if kind == "core":
            result = NovaMatcher(r, **options).check_prompt(text)
            matched = result["matched"]
        elif kind == "scanner":
            result = NovaScanner([r], **options).scan_with_details(text)
            matched = result["matched_any"]
            assert "Risk" in result["decision_results"]
        else:
            result = Nova(rules=[r], **options).scan(text)
            matched = bool(result.matches)
            assert "Risk" in result.decision_results
        assert matched is expected
        assert len(evaluator.calls) == calls
        if condition == "all of llm":
            assert len(evaluator.calls[0][0]) == 3


def test_unknown_never_becomes_negative_or_allowed():
    nova = Nova(rules=[rule("not llm.$operation")], decision_config={"enabled": True}, decision_evaluator=FixtureEvaluator(.4))
    with pytest.raises(NovaEvaluationError) as caught:
        nova.scan("synthetic")
    result = caught.value.partial_result
    assert not result.allowed and not result.clean and not result.evaluation_complete
    assert caught.value.causes == ["insufficient_confidence"]
    assert result.decision_results["Risk"]["$operation"]["answer"]["confidence"] == .4


def test_definite_block_skips_unresolved_decision_checks():
    legacy = NovaParser().parse('rule Block {\nkeywords:\n$x = "secret"\ncondition:\n$x\n}')
    nova = Nova(rules=[rule(), legacy], default_action=Action.BLOCK)
    for context in (None, {"unsupported": object()}):
        result = nova.scan("secret", decision_state=context)
        assert result.blocked and result.evaluation_complete
        assert result.blocked_rules == ["Block"]
        assert not result.allowed
        assert all(entry["reason"] == "early_block" for entry in result.decision_results["Risk"].values())


@pytest.mark.parametrize("action", [Action.BLOCK, Action.FLAG])
@pytest.mark.parametrize("parallel", [False, True])
def test_keyword_block_skips_models_but_flag_does_not(action, parallel):
    keyword = NovaParser().parse('rule Keyword {\nkeywords:\n$x = "secret"\ncondition:\n$x\n}')
    legacy_llm = NovaParser().parse('rule LegacyLlm {\nllm:\n$x = "Unsafe?"(0.1)\ncondition:\nllm.$x\n}')
    evaluator = FixtureEvaluator(noul=.1)
    nova = Nova(rules=[rule("llm.$scope"), legacy_llm, keyword],
                default_action=action, decision_config={"enabled": True}, decision_evaluator=evaluator)
    llm = Mock()
    llm.evaluate_prompt.return_value = (False, .9, {})
    nova._matchers["LegacyLlm"].llm_evaluator = llm
    result = nova.scan("secret", parallel=parallel)
    expected_calls = 0 if action == Action.BLOCK else 1
    assert len(evaluator.calls) == expected_calls
    assert llm.evaluate_prompt.call_count == expected_calls
    assert result.evaluation_complete
    assert result.blocked == (action == Action.BLOCK)


def test_llm_remains_independent_and_uses_temperature():
    r = rule("llm.$scope and llm.$intent", extra='llm:\n$intent = "Suspicious?"(0.3)\n')
    evaluator = FixtureEvaluator()
    llm = Mock()
    llm.evaluate_prompt.return_value = (True, .9, {})
    matcher = NovaMatcher(r, llm_evaluator=llm, decision_config={"enabled": True}, decision_evaluator=evaluator)
    assert matcher.check_prompt("synthetic")["matched"]
    assert llm.evaluate_prompt.call_args.kwargs == {"temperature": .3}
    with pytest.raises(NovaEvaluationError):
        matcher.check_prompt("synthetic", skip_llm=True)
    assert len(evaluator.calls) == 1


def test_sdk_batches_once_and_keeps_nonmatching_evidence():
    evaluator = FixtureEvaluator(noul=.1)
    nova = Nova(rules=[rule("llm.$scope")], decision_config={"enabled": True}, decision_evaluator=evaluator)
    result = nova.scan("action", decision_state={"goal": "test"})
    assert result.clean
    assert result.decision_results["Risk"]["$scope"]["answer"]["noul"] == .1
    assert len(evaluator.calls) == 1
    assert evaluator.calls[0][1] == {"text": "action", "context": {"goal": "test"}}
    assert result.decision_results["Risk"]["$risk"]["status"] == "skipped"
    assert result.to_dict()["evaluation_complete"]


def test_disabled_and_skip_decision_never_call_injected_evaluator(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-key")
    for options, skip in [({}, False), ({"enabled": True}, True)]:
        evaluator = FixtureEvaluator()
        nova = Nova(rules=[rule()], decision_config=options, decision_evaluator=evaluator)
        with pytest.raises(NovaEvaluationError):
            nova.scan("synthetic", skip_decision=skip)
        assert not evaluator.calls


def test_concurrent_scans_have_separate_state_and_evidence():
    evaluator = FixtureEvaluator()
    nova = Nova(rules=[rule()], decision_config={"enabled": True}, decision_evaluator=evaluator)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda i: nova.scan(str(i), decision_state={"id": i}), range(20)))
    assert len(evaluator.calls) == 20
    assert all(state["text"] == str(state["context"]["id"]) for _, state in evaluator.calls)
    assert len({id(result.decision_results) for result in results}) == 20


@pytest.mark.parametrize("async_mode", [False, True])
def test_protection_never_executes_after_unresolved_evaluation(async_mode):
    nova = Nova(rules=[rule()])
    calls = []
    factory = Mock(return_value={"goal": "test"})

    @nova.protect(raise_on_block=False, decision_state_factory=factory)
    def run(prompt):
        calls.append(prompt)

    @nova.protect(raise_on_block=False, decision_state_factory=factory)
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
    nova = Nova(rules=[rule("llm.$scope")], decision_config={"enabled": True}, decision_evaluator=evaluator)

    class Tool:
        @protect(nova_instance=nova, decision_state_factory=lambda args: {"goal": args["goal"]})
        def run(self, goal, prompt="synthetic"):
            return prompt

    assert Tool().run("test") == "synthetic"
    assert evaluator.calls[-1][1]["context"] == {"goal": "test"}
    assert scan("synthetic", nova_instance=nova).clean
    assert asyncio.run(scan_async("synthetic", nova_instance=nova)).clean


def test_dynamic_rule_uses_shared_configuration():
    evaluator = FixtureEvaluator()
    nova = Nova(decision_config={"enabled": True}, decision_evaluator=evaluator)
    nova.add_rule(rule())
    assert nova.scan("synthetic").match_count == 1
    scanner = NovaScanner(decision_config={"enabled": True}, decision_evaluator=evaluator)
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


def test_sdk_mixed_file_uses_structural_boundaries(tmp_path):
    path = tmp_path / "mixed.nov"
    path.write_text("// file comment\n" + source(name="First") + "\n# between rules\n" + source(name="Second"))
    nova = Nova(rules_path=path, decision_config={"enabled": True}, decision_evaluator=FixtureEvaluator())
    result = nova.scan("synthetic")
    assert result.match_count == 2
    assert set(result.decision_results) == {"First", "Second"}


def test_indeterminate_check_can_be_irrelevant_after_llm_answer():
    r = rule("llm.$operation or llm.$intent", extra='llm:\n$intent = "Intent?"(0.2)\n')
    llm = Mock()
    llm.evaluate_prompt.return_value = (True, .9, {})
    matcher = NovaMatcher(r, llm_evaluator=llm, decision_config={"enabled": True}, decision_evaluator=FixtureEvaluator(.3))
    result = matcher.check_prompt("synthetic")
    assert result["matched"] and result["evaluation_complete"]
    assert result["decision_results"]["$operation"]["reason"] == "insufficient_confidence"


def test_state_does_not_leak_into_keyword_input():
    r = rule("keywords.$key and llm.$scope", extra='keywords:\n$key = "credential"\n')
    evaluator = FixtureEvaluator()
    nova = Nova(rules=[r], decision_config={"enabled": True}, decision_evaluator=evaluator)
    assert nova.scan("read README", decision_state={"history": "credential"}).clean
    assert not evaluator.calls


def test_irrelevant_invalid_context_agrees_across_entry_points():
    r = rule("keywords.$key or llm.$scope", extra='keywords:\n$key = "secret"\n')
    context = {"invalid": object()}
    assert NovaMatcher(r).check_prompt("secret", decision_state=context)["matched"]
    assert NovaScanner([r]).scan_with_details("secret", decision_state=context)["matched_any"]
    assert Nova(rules=[r]).scan("secret", decision_state=context).matches


@pytest.mark.parametrize("kind", ["llm", "decision"])
@pytest.mark.parametrize("add_after_decoration", [False, True])
@pytest.mark.parametrize("async_mode", [False, True])
def test_protection_scans_default_prompt_with_current_rules(kind, add_after_decoration, async_mode, monkeypatch):
    from nova.sdk.exceptions import NovaBlockedError

    evaluator = FixtureEvaluator()
    nova = Nova(default_action=Action.BLOCK, decision_config={"enabled": True}, decision_evaluator=evaluator)
    llm = Mock()
    llm.evaluate_prompt.return_value = (True, .9, {})
    monkeypatch.setattr(nova, "_create_configured_llm_evaluator", lambda: llm)
    detection = rule("llm.$scope") if kind == "decision" else NovaParser().parse(
        'rule Llm {\nllm:\n$x = "Unsafe?"(0.1)\ncondition:\nllm.$x\n}')
    if not add_after_decoration:
        nova.add_rule(detection)
    calls = []

    def run(prompt="synthetic"):
        calls.append(prompt)

    async def run_async(prompt="synthetic"):
        calls.append(prompt)

    protected = nova.protect()(run_async if async_mode else run)
    if add_after_decoration:
        nova.add_rule(detection)
    with pytest.raises(NovaBlockedError):
        if async_mode:
            asyncio.run(protected())
        else:
            protected()
    assert not calls
    assert len(evaluator.calls) == (1 if kind == "decision" else 0)
    assert llm.evaluate_prompt.call_count == (1 if kind == "llm" else 0)


@pytest.mark.parametrize("async_mode", [False, True])
def test_protection_keeps_skip_decision_after_dynamic_rule_addition(async_mode):
    evaluator = FixtureEvaluator()
    nova = Nova(decision_config={"enabled": True}, decision_evaluator=evaluator)
    calls = []

    def run(prompt):
        calls.append(prompt)

    async def run_async(prompt):
        calls.append(prompt)

    protected = nova.protect(skip_decision=True)(run_async if async_mode else run)
    nova.add_rule(rule("llm.$scope"))
    with pytest.raises(NovaEvaluationError):
        if async_mode:
            asyncio.run(protected("synthetic"))
        else:
            protected("synthetic")
    assert not evaluator.calls and not calls
