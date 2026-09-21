"""Minimal transport boundary; no provider package is needed for parsing."""

from typing import Protocol
from nova.core.sys1 import Sys1Batch, Sys1Pattern


class Sys1Evaluator(Protocol):
    def evaluate_many(self, patterns: dict[str, Sys1Pattern], state) -> Sys1Batch:
        ...
