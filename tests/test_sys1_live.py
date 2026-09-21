"""Explicit opt-in, synthetic data, one mixed request and at most two attempts."""

import os
import pytest
from nova.evaluators.sys1.config import Sys1Config
from nova.evaluators.sys1.openrouter import OpenRouterSys1Evaluator
from test_sys1_evaluator import NOUL, CHOICE, SCORE


@pytest.mark.skipif(os.getenv("NOVA_SYS1_LIVE_TEST") != "1" or not os.getenv("OPENROUTER_API_KEY"),
                    reason="Live Sys1 requests require explicit opt-in and credentials")
def test_live_mixed_synthetic_request():
    evaluator = OpenRouterSys1Evaluator(Sys1Config(enabled=True, retries=1))
    batch = evaluator.evaluate_many({"$n": NOUL, "$c": CHOICE, "$s": SCORE},
                                    {"approved_task": "Read a public sample file", "current_action": "Read sample.txt"})
    assert all(entry.answer is not None for entry in batch.evaluations.values())
