"""Explicit local smoke test: NOVA_LAYA_LIVE_TEST=1 plus a prepared model path."""

from dataclasses import replace
import os
import socket

import pytest

from nova.core.sys1 import Predicate
from nova.evaluators.sys1.laya import LayaSys1Evaluator
from nova.evaluators.sys1.models import validate_model
from test_laya import patterns


@pytest.mark.skipif(os.environ.get("NOVA_LAYA_LIVE_TEST") != "1" or not os.environ.get("NOVA_LAYA_MODEL"),
                    reason="Requires explicit opt-in and prepared local checkpoint")
def test_real_mixed_batch_without_network(monkeypatch):
    attempts = []
    def denied(*args, **kwargs):
        attempts.append(1)
        raise AssertionError("Local inference must not access the network")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    e = LayaSys1Evaluator({"enabled": True, "provider": "laya", "model": os.environ["NOVA_LAYA_MODEL"],
                          "device": os.environ.get("NOVA_LAYA_DEVICE", "cpu")})
    checks = patterns()
    checks["$c"] = replace(checks["$c"], min_confidence=None)
    checks["$s"] = replace(checks["$s"], min_confidence=None)
    for _ in range(2):
        result = e.evaluate_many(checks, "Read the public README file.")
        assert all(entry.status == "evaluated" and entry.predicate is not Predicate.UNKNOWN
                   for entry in result.evaluations.values()), result
        assert result.metadata["inference_count"] == 1
        assert result.metadata["revision"]
    assert not attempts
    validate_model(os.environ["NOVA_LAYA_MODEL"])  # Runtime must not rewrite prepared assets.
