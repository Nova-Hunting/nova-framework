"""Provider-independent Sys1 declarations and evidence."""

from dataclasses import dataclass, field
from enum import Enum
import math
import re
from typing import Any, Optional, Union


class Predicate(Enum):
    FALSE = "false"
    TRUE = "true"
    UNKNOWN = "unknown"

    def __bool__(self):
        raise TypeError("Compare predicates explicitly; UNKNOWN is not False")


def number(value, name, maximum=1.0):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{name} must be a number")
    if not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be finite and within [0, {maximum}]")


def description(value, name="instructions"):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


@dataclass(frozen=True)
class NoulPattern:
    instructions: str
    true_criteria: str
    false_criteria: str
    threshold: float

    def __post_init__(self):
        description(self.instructions)
        description(self.true_criteria, "true")
        description(self.false_criteria, "false")
        number(self.threshold, "threshold")


@dataclass(frozen=True)
class ChoicePattern:
    instructions: str
    options: dict[str, str]
    match: tuple[str, ...]
    min_confidence: Optional[float] = None

    def __post_init__(self):
        description(self.instructions)
        if not isinstance(self.options, dict) or not 2 <= len(self.options) <= 10:
            raise ValueError("Choice requires 2–10 options")
        for key, value in self.options.items():
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_]+", key):
                raise ValueError("Invalid Choice option identifier")
            description(value, "option description")
        if not isinstance(self.match, (tuple, list)) or not self.match:
            raise ValueError("Choice match must be a nonempty list")
        if any(not isinstance(key, str) or key not in self.options for key in self.match):
            raise ValueError("Choice match references an undefined option")
        if len(set(self.match)) != len(self.match):
            raise ValueError("Duplicate Choice match entry")
        if self.min_confidence is not None:
            number(self.min_confidence, "min_confidence")
        object.__setattr__(self, "options", dict(self.options))
        object.__setattr__(self, "match", tuple(self.match))


@dataclass(frozen=True)
class ScorePattern:
    instructions: str
    levels: tuple[str, ...]
    threshold: float
    min_confidence: Optional[float] = None

    def __post_init__(self):
        description(self.instructions)
        if not isinstance(self.levels, (tuple, list)) or not 2 <= len(self.levels) <= 10:
            raise ValueError("Score requires 2–10 levels")
        for level in self.levels:
            description(level, "level")
        number(self.threshold, "threshold", len(self.levels) - 1)
        if self.min_confidence is not None:
            number(self.min_confidence, "min_confidence")
        object.__setattr__(self, "levels", tuple(self.levels))


Sys1Pattern = Union[NoulPattern, ChoicePattern, ScorePattern]


@dataclass(frozen=True)
class NoulAnswer:
    noul: float


@dataclass(frozen=True)
class ChoiceAnswer:
    choice: str
    confidence: Optional[float] = None
    probabilities: Optional[dict[str, float]] = None


@dataclass(frozen=True)
class ScoreAnswer:
    score: float
    confidence: Optional[float] = None
    probabilities: Optional[dict[str, float]] = None
    legend: Optional[dict[str, str]] = None


Sys1Answer = Union[NoulAnswer, ChoiceAnswer, ScoreAnswer]


def primitive(pattern):
    return {NoulPattern: "noul", ChoicePattern: "choice", ScorePattern: "score"}[type(pattern)]


@dataclass
class Sys1Evaluation:
    primitive: str
    predicate: Predicate = Predicate.UNKNOWN
    status: str = "pending"
    reason: Optional[str] = None
    answer: Optional[Sys1Answer] = None
    settings: dict[str, Any] = field(default_factory=dict)
    question_id: Optional[str] = None
    requested_model: Optional[str] = None
    returned_model: Optional[str] = None
    request_id: Optional[str] = None
    provider: Optional[str] = None

    def to_dict(self):
        from dataclasses import asdict
        result = asdict(self)
        result["predicate"] = self.predicate.value
        # Omitted provider metadata remains absent, not an invented value.
        if result["answer"] is not None:
            result["answer"] = {k: v for k, v in result["answer"].items() if v is not None}
        return result


@dataclass
class Sys1Batch:
    evaluations: dict[str, Sys1Evaluation]
    metadata: dict[str, Any] = field(default_factory=dict)


class NovaEvaluationError(Exception):
    """A required predicate is unresolved; partial_result retains definite findings."""

    def __init__(self, partial_result, causes):
        self.partial_result = partial_result
        self.result = partial_result
        self.causes = causes
        super().__init__("Required evaluation is incomplete: " + ", ".join(sorted(set(causes))))
