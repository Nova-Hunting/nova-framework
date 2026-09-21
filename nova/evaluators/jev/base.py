"""Minimal transport boundary; no provider package is needed for parsing."""

from typing import Protocol
from nova.core.jev import JevBatch, JevPattern


class JevEvaluator(Protocol):
    def evaluate_many(self, patterns: dict[str, JevPattern], state) -> JevBatch:
        ...
