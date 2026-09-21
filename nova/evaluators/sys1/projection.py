"""Pure request compilation, response validation and predicate projection."""

from dataclasses import asdict
from nova.core.sys1 import (
    NoulPattern, ChoicePattern, NoulAnswer, ChoiceAnswer, ScoreAnswer,
    Sys1Evaluation, Predicate, number, primitive,
)


def question(pattern):
    if isinstance(pattern, NoulPattern):
        criteria = {"true": pattern.true_criteria, "false": pattern.false_criteria}
    elif isinstance(pattern, ChoicePattern):
        criteria = dict(pattern.options)
    else:
        criteria = list(pattern.levels)
    return {"type": primitive(pattern), "instructions": pattern.instructions, "criteria": criteria}


def record(pattern, **kwargs):
    fields = asdict(pattern)
    settings = {key: fields[key] for key in ("threshold", "match", "min_confidence") if key in fields}
    return Sys1Evaluation(primitive(pattern), settings=settings, **kwargs)


def validate_answer(pattern, raw, *, decimal_places=2):
    if not isinstance(raw, dict) or raw.get("type") != primitive(pattern):
        raise ValueError("Wrong or missing answer type")
    if isinstance(pattern, NoulPattern):
        number(raw.get("noul"), "noul")
        return NoulAnswer(raw["noul"])
    confidence = raw.get("confidence")
    if confidence is not None:
        number(confidence, "confidence")
    probabilities = raw.get("probabilities")
    keys = set(pattern.options) if isinstance(pattern, ChoicePattern) else {str(i) for i in range(len(pattern.levels))}
    if probabilities is not None:
        if not isinstance(probabilities, dict) or set(probabilities) != keys:
            raise ValueError("Probability entries do not match declared criteria")
        for value in probabilities.values():
            number(value, "probability")
        # Precision is a transport contract; never silently renormalize.
        rounding = .5 * 10 ** -decimal_places
        if abs(sum(probabilities.values()) - 1.0) > rounding * len(keys) + 1e-8:
            raise ValueError("Probabilities do not sum to one within rounding tolerance")
        probabilities = dict(probabilities)
    if isinstance(pattern, ChoicePattern):
        choice = raw.get("choice")
        if not isinstance(choice, str) or choice not in pattern.options:
            raise ValueError("Unknown selected option")
        return ChoiceAnswer(choice, confidence, probabilities)
    score = raw.get("score")
    number(score, "score", len(pattern.levels) - 1)
    legend = raw.get("legend")
    if legend is not None and legend != {str(i): level for i, level in enumerate(pattern.levels)}:
        raise ValueError("Legend does not match declared levels")
    if probabilities is not None:
        weighted = sum(int(key) * value for key, value in probabilities.items())
        rounding = .5 * 10 ** -decimal_places
        tolerance = rounding * (sum(range(len(pattern.levels))) + 1) + 1e-8
        if abs(weighted - score) > tolerance:
            raise ValueError("Score is inconsistent with probabilities")
    return ScoreAnswer(score, confidence, probabilities, dict(legend) if legend is not None else None)


def project(pattern, answer):
    result = record(pattern, answer=answer, status="evaluated")
    if isinstance(pattern, NoulPattern):
        matched = answer.noul >= pattern.threshold
    else:
        if pattern.min_confidence is not None:
            if answer.confidence is None:
                result.status, result.reason = "indeterminate", "missing_confidence"
                return result
            if answer.confidence < pattern.min_confidence:
                result.status, result.reason = "indeterminate", "insufficient_confidence"
                return result
        matched = answer.choice in pattern.match if isinstance(pattern, ChoicePattern) else answer.score >= pattern.threshold
    result.predicate = Predicate.TRUE if matched else Predicate.FALSE
    return result
