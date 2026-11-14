"""Minimal transport boundary; no provider package is needed for parsing."""

from typing import Protocol
from nova.core.decision import DecisionBatch, DecisionPattern


class DecisionEvaluator(Protocol):
    def evaluate_many(self, patterns: dict[str, DecisionPattern], state) -> DecisionBatch:
        ...
