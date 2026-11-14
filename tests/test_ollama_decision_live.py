"""Explicit opt-in System One smoke test; never installs or downloads models."""

import os

import pytest

from nova.evaluators.decision.ollama import OllamaDecisionEvaluator
from test_decision_evaluator import NOUL, CHOICE, SCORE


@pytest.mark.skipif(os.getenv("NOVA_OLLAMA_DECISION_LIVE_TEST") != "1" or not os.getenv("NOVA_OLLAMA_DECISION_MODEL"),
                    reason="Live Ollama requests require explicit opt-in and an installed decision model")
def test_live_ollama_mixed_request():
    evaluator = OllamaDecisionEvaluator({"enabled": True, "provider": "ollama", "retries": 0,
                                         "model": os.environ["NOVA_OLLAMA_DECISION_MODEL"]})
    batch = evaluator.evaluate_many({"$n": NOUL, "$c": CHOICE, "$s": SCORE}, "Read the public README")
    assert all(entry.answer is not None for entry in batch.evaluations.values())
    assert batch.metadata["request_count"] == 1
    assert batch.metadata["provider"] == "ollama"
