from unittest.mock import Mock

import pytest

from nova.core.parser import NovaParser, NovaParserError
from nova.core.matcher import NovaMatcher
from nova.core.decision import DecisionBatch, NovaEvaluationError
from nova.evaluators.decision.projection import validate_answer, project
from nova.sdk import Nova


MIXED = '''rule Mixed {
llm:
    $quoted = "LLM question?" (0.3)
    $yes = noul "Active override?" {
        true = "An active override"
        false = "Benign discussion"
        threshold = 0.75
    }
    $category = choice "Which category?" {
        options = {
            active = "Active request"
            ordinary = "Ordinary request"
        }
        match = ["active"]
    }
    $degree = score "How direct?" {
        levels = ["No request", "Explicit request"]
        threshold = 0.5
    }
condition:
    all of llm
}'''


class TypedEvaluator:
    def __init__(self):
        self.calls = []

    def evaluate_many(self, patterns, state):
        self.calls.append((patterns, state))
        answers = {
            "$yes": {"type": "noul", "noul": .9},
            "$category": {"type": "choice", "choice": "active"},
            "$degree": {"type": "score", "score": .8},
        }
        return DecisionBatch({k: project(p, validate_answer(p, answers[k])) for k, p in patterns.items()})


def test_mixed_llm_declarations_and_quantifier():
    rule = NovaParser().parse(MIXED)
    typed = TypedEvaluator()
    quoted = Mock()
    quoted.evaluate_prompt.return_value = (True, .9, {})
    matcher = NovaMatcher(rule, llm_evaluator=quoted, decision_config={"enabled": True}, decision_evaluator=typed)
    result = matcher.check_prompt("input", decision_state={"task": "test"})
    assert result["matched"]
    assert set(result["matching_llm"]) == {"$quoted", "$yes", "$category", "$degree"}
    assert len(typed.calls) == 1
    assert typed.calls[0][1] == {"text": "input", "context": {"task": "test"}}
    assert quoted.evaluate_prompt.call_args.kwargs == {"temperature": .3}
    quoted.evaluate_prompt.return_value = (False, .9, {})
    assert not matcher.check_prompt("input")["matched"]


def test_same_variable_cannot_be_reused_between_quoted_and_typed_checks():
    with pytest.raises(NovaParserError, match="[Dd]uplicate"):
        NovaParser().parse(MIXED.replace('$yes = noul', '$quoted = noul'))


@pytest.mark.parametrize("section", ["decision", "detection", "jev", "sys1"])
def test_removed_section_names_are_rejected(section):
    with pytest.raises(NovaParserError, match="llm"):
        NovaParser().parse(MIXED.replace('llm:', section + ':'))


def test_typed_only_llm_does_not_initialize_chat_provider(monkeypatch):
    rule = NovaParser().parse(MIXED.replace('    $quoted = "LLM question?" (0.3)\n', ''))
    create = Mock(side_effect=AssertionError("No chat provider required"))
    monkeypatch.setattr(Nova, "_create_configured_llm_evaluator", create)
    typed = TypedEvaluator()
    nova = Nova(rules=[rule], decision_config={"enabled": True}, decision_evaluator=typed)
    assert nova.scan("input").matches
    create.assert_not_called()
    with pytest.raises(NovaEvaluationError):
        nova.scan("input", skip_llm=True)
    assert len(typed.calls) == 1


def test_skip_typed_checks_keeps_quoted_llm_checks_available():
    rule = NovaParser().parse(MIXED.replace("all of llm", "llm.$quoted or llm.$yes"))
    typed = TypedEvaluator()
    quoted = Mock()
    quoted.evaluate_prompt.return_value = (True, .9, {})
    matcher = NovaMatcher(rule, llm_evaluator=quoted, decision_config={"enabled": True}, decision_evaluator=typed)
    assert matcher.check_prompt("input", skip_decision=True)["matched"]
    assert not typed.calls
    quoted.evaluate_prompt.assert_called_once()


def test_removed_condition_namespace_is_rejected():
    with pytest.raises(NovaParserError):
        NovaParser().parse(MIXED.replace("all of llm", "decision.$yes"))


def test_quoted_primitive_text_keeps_quoted_llm_path():
    from nova.core.decision_parser import has_typed_llm

    text = '$check = "Explain this syntax: $example = noul" (0.2)'
    assert not has_typed_llm(text)
    rule = NovaParser().parse('rule Quoted {\nllm:\n' + text + '\ncondition:\nllm.$check\n}')
    assert not rule.decision
    assert rule.llms["$check"].pattern == "Explain this syntax: $example = noul"
    assert rule.llms["$check"].threshold == .2
