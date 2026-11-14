"""Explicit opt-in, synthetic data, one mixed request and at most two attempts."""

import os
import pytest
from nova.evaluators.decision.config import DecisionConfig
from nova.evaluators.decision.openrouter import OpenRouterDecisionEvaluator
from test_decision_evaluator import NOUL, CHOICE, SCORE


@pytest.mark.skipif(os.getenv("NOVA_DECISION_LIVE_TEST") != "1" or not os.getenv("OPENROUTER_API_KEY"),
                    reason="Live Decision requests require explicit opt-in and credentials")
def test_live_mixed_synthetic_request():
    evaluator = OpenRouterDecisionEvaluator(DecisionConfig(enabled=True, retries=1))
    batch = evaluator.evaluate_many({"$n": NOUL, "$c": CHOICE, "$s": SCORE},
                                    {"approved_task": "Read a public sample file", "current_action": "Read sample.txt"})
    assert all(entry.answer is not None for entry in batch.evaluations.values())
