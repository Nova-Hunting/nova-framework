import pytest

from nova.core.rules import KeywordPattern, LLMPattern, NovaRule
from nova.core.scanner import NovaScanner
from nova.evaluators.llm import OpenRouterEvaluator


def make_llm_rule(condition="llm.$judge", name="ScannerLLMRule"):
    return NovaRule(
        name=name,
        keywords={"$safe": KeywordPattern("safe")},
        llms={"$judge": LLMPattern("Detect if the text is unsafe")},
        condition=condition,
    )


def make_keyword_rule(name):
    return NovaRule(
        name=name,
        keywords={"$safe": KeywordPattern("safe")},
        condition="keywords.$safe",
    )


def test_scanner_uses_configured_openrouter_evaluator_without_llm_call(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("OPENROUTER_LLM_MODEL", "anthropic/claude-sonnet-4")

    rule = make_llm_rule("keywords.$safe or llm.$judge")
    scanner = NovaScanner([rule], llm_type="openrouter")

    assert isinstance(scanner._llm_evaluator, OpenRouterEvaluator)
    assert scanner._llm_evaluator.model == "anthropic/claude-sonnet-4"

    results = scanner.scan("this prompt is safe")

    assert len(results) == 1
    assert results[0]["matched"] is True
    assert results[0]["matching_keywords"] == {"$safe": True}
    assert results[0]["debug"]["all_llm_matches"] == {}


def test_scanner_reuses_injected_llm_evaluator():
    class FakeLLMEvaluator:
        model = "fake-model"

        def __init__(self):
            self.calls = []

        def evaluate_prompt(self, prompt_template, text, temperature=0.1):
            self.calls.append((prompt_template, text, temperature))
            return True, 0.91, {
                "evaluator_type": "fake",
                "model": self.model,
                "reason": "matched by fake evaluator",
            }

    fake_evaluator = FakeLLMEvaluator()
    scanner = NovaScanner([make_llm_rule()], llm_evaluator=fake_evaluator)

    results = scanner.scan("suspicious prompt")

    assert len(results) == 1
    assert results[0]["matched"] is True
    assert results[0]["matching_llm"] == {"$judge": True}
    assert results[0]["llm_scores"] == {"$judge": 0.91}
    assert fake_evaluator.calls == [("Detect if the text is unsafe", "suspicious prompt", 0.1)]


def test_scanner_explicit_openrouter_provider_requires_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        NovaScanner([make_llm_rule()], llm_type="openrouter")


def test_scanner_constructor_rejects_duplicate_rule_names():
    with pytest.raises(ValueError, match="Duplicate rule name"):
        NovaScanner([
            make_keyword_rule("DuplicateRule"),
            make_keyword_rule("DuplicateRule"),
        ])


def test_scanner_add_rule_uses_configured_openrouter_evaluator(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")

    scanner = NovaScanner(llm_type="openrouter", llm_model="google/gemini-2.5-pro")
    scanner.add_rule(make_llm_rule("keywords.$safe or llm.$judge"))

    assert isinstance(scanner._llm_evaluator, OpenRouterEvaluator)
    assert scanner._llm_evaluator.model == "google/gemini-2.5-pro"


def test_scanner_add_rules_rejects_duplicates_without_partial_mutation():
    scanner = NovaScanner([make_keyword_rule("ExistingRule")])
    original_rule_names = scanner.get_rule_names()

    with pytest.raises(ValueError, match="Duplicate rule name"):
        scanner.add_rules([
            make_keyword_rule("NewRule"),
            make_keyword_rule("NewRule"),
        ])

    assert scanner.get_rule_names() == original_rule_names

    with pytest.raises(ValueError, match="ExistingRule"):
        scanner.add_rules([make_keyword_rule("ExistingRule")])

    assert scanner.get_rule_names() == original_rule_names
