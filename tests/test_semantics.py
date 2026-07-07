import builtins

from nova.core.rules import SemanticPattern
from nova.evaluators.semantics import DefaultSemanticEvaluator


def test_semantic_evaluator_fails_closed_when_optional_dependency_missing(monkeypatch):
    original_import = builtins.__import__

    def block_sentence_transformers(name, *args, **kwargs):
        if name == "sentence_transformers" or name.startswith("sentence_transformers."):
            raise ImportError("sentence-transformers is not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_sentence_transformers)

    evaluator = DefaultSemanticEvaluator(model_name="unit-test-missing-semantic-model")
    matched, score = evaluator.evaluate(SemanticPattern("sensitive instruction", threshold=0.5), "sensitive instruction")

    assert matched is False
    assert score == 0.0
    assert evaluator.last_error is not None
