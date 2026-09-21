"""Scan-local staged evaluation for rules containing Sys1 declarations."""

from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor

from nova.core.sys1 import Predicate, NovaEvaluationError
from .condition import compile_condition, declarations
from .projection import record
from .state import snapshot_state


@dataclass
class Progress:
    values: dict = field(default_factory=dict)
    sys1: dict = field(default_factory=dict)
    errors: dict = field(default_factory=dict)
    semantic_scores: dict = field(default_factory=dict)
    llm_scores: dict = field(default_factory=dict)
    llm_details: dict = field(default_factory=dict)
    batches: list = field(default_factory=list)


def evaluate(matcher, text, state, *, skip_llm=False, skip_sys1=False, fast=False, progress=None):
    rule = matcher.rule
    node = compile_condition(rule)
    progress = progress or Progress(sys1={name: record(pattern) for name, pattern in rule.sys1.items()})
    groups = declarations(rule)
    for section in ("keywords", "semantics", "sys1", "llm"):
        if fast and section in ("sys1", "llm"):
            break
        needed = node.needed(progress.values)
        patterns = {name: pattern for name, pattern in groups[section].items()
                    if f"{section}.{name}" in needed and f"{section}.{name}" not in progress.errors
                    and f"{section}.{name}" not in progress.values}
        if not patterns:
            continue
        if section == "sys1":
            if skip_sys1 or not matcher.sys1_config.enabled:
                for name in patterns:
                    progress.sys1[name].status = "unavailable"
                    progress.sys1[name].reason = "skipped" if skip_sys1 else "disabled"
            else:
                try:
                    batch = matcher.sys1_evaluator.evaluate_many(patterns, state)
                    progress.batches.append(batch.metadata)
                    for name in patterns:
                        entry = batch.evaluations.get(name)
                        if entry is None or not isinstance(entry.predicate, Predicate):
                            progress.sys1[name].status, progress.sys1[name].reason = "error", "missing_answer"
                        else:
                            progress.sys1[name] = entry
                except Exception:
                    for name in patterns:
                        progress.sys1[name].status, progress.sys1[name].reason = "error", "evaluator_error"
            for name in patterns:
                entry = progress.sys1[name]
                progress.values[f"sys1.{name}"] = entry.predicate
                if entry.predicate is Predicate.UNKNOWN:
                    progress.errors[f"sys1.{name}"] = entry.reason or "unavailable"
            continue
        for name, pattern in patterns.items():
            ref = f"{section}.{name}"
            if ref not in node.needed(progress.values):
                continue
            try:
                if section == "keywords":
                    matched = matcher.keyword_evaluator.evaluate(pattern, text, name)
                elif section == "semantics":
                    if matcher.semantic_evaluator is None:
                        raise RuntimeError("unavailable")
                    matched, score = matcher.semantic_evaluator.evaluate(pattern, text)
                    if getattr(matcher.semantic_evaluator, "last_error", None):
                        raise RuntimeError("evaluation_error")
                    progress.semantic_scores[name] = score
                else:
                    if skip_llm or matcher.llm_evaluator is None:
                        raise RuntimeError("unavailable")
                    matched, confidence, details = matcher.llm_evaluator.evaluate_prompt(
                        pattern.pattern, text, temperature=pattern.threshold)
                    if isinstance(details, dict) and details.get("error"):
                        raise RuntimeError("evaluation_error")
                    progress.llm_scores[name], progress.llm_details[name] = confidence, details
                progress.values[ref] = Predicate.TRUE if matched else Predicate.FALSE
            except Exception:
                progress.errors[ref] = section + "_unavailable"
                progress.values[ref] = Predicate.UNKNOWN
    outcome = node.evaluate(progress.values)
    if not fast or outcome is not Predicate.UNKNOWN:
        for entry in progress.sys1.values():
            if entry.status == "pending":
                entry.status, entry.reason = "skipped", "condition_determined" if outcome is not Predicate.UNKNOWN else "unreferenced"
    matches = {section: {name: True for name in patterns if progress.values.get(f"{section}.{name}") is Predicate.TRUE}
               for section, patterns in groups.items()}
    result = {
        "matched": outcome is Predicate.TRUE, "rule_name": rule.name, "meta": rule.meta,
        "matching_keywords": matches["keywords"], "matching_semantics": matches["semantics"],
        "matching_llm": matches["llm"], "matching_sys1": matches["sys1"],
        "semantic_scores": progress.semantic_scores, "llm_scores": progress.llm_scores,
        "sys1_results": {name: entry.to_dict() for name, entry in progress.sys1.items()},
        "sys1_batches": progress.batches, "evaluation_complete": outcome is not Predicate.UNKNOWN,
        "debug": {"condition": rule.condition, "condition_result": outcome.value,
                  "evaluation_warnings": [f"{ref}: {reason}" for ref, reason in progress.errors.items()],
                  "all_keyword_matches": {key: progress.values[f"keywords.{key}"] is Predicate.TRUE for key in rule.keywords if f"keywords.{key}" in progress.values},
                  "all_semantic_matches": {}, "all_llm_matches": {}, "all_llm_details": progress.llm_details},
    }
    if outcome is Predicate.UNKNOWN and not fast:
        raise NovaEvaluationError(result, [progress.errors.get(ref, "unavailable") for ref in node.needed(progress.values)])
    return result, progress


def collect(rules, matchers, original_text, text, *, context=None, skip_llm=False, skip_sys1=False, parallel=True):
    """Fast pass then model pass, retaining evidence locally and all definite findings."""
    sys1_matchers = [matchers[rule.name] for rule in rules if rule.sys1]
    limit = min(matcher.sys1_config.max_request_bytes for matcher in sys1_matchers)
    invalid_state = False
    try:
        state = snapshot_state(original_text, context, limit)
    except (ValueError, RecursionError, UnicodeError):
        state, invalid_state = None, True
    results, pending, causes = {}, [], []
    for rule in rules:
        matcher = matchers[rule.name]
        if rule.sys1:
            result, progress = evaluate(matcher, text, state, fast=True)
            results[rule.name] = result
            if not result["evaluation_complete"]:
                pending.append((rule, progress))
        else:
            result = matcher.check_prompt(text, skip_llm=True)
            results[rule.name] = result
            if rule.llms and not skip_llm and not result["matched"]:
                from nova.evaluators.condition import can_llm_change_outcome
                debug = result.get("debug", {})
                if can_llm_change_outcome(rule.condition, debug.get("all_keyword_matches", {}),
                                          debug.get("all_semantic_matches", {})):
                    pending.append((rule, None))

    def finish(item):
        rule, progress = item
        if not rule.sys1:
            return rule.name, matchers[rule.name].check_prompt(text), []
        if invalid_state:
            for name in rule.sys1:
                progress.values[f"sys1.{name}"] = Predicate.UNKNOWN
                progress.errors[f"sys1.{name}"] = "invalid_state"
                progress.sys1[name].status, progress.sys1[name].reason = "error", "invalid_state"
        try:
            result, _ = evaluate(matchers[rule.name], text, state, skip_llm=skip_llm,
                                 skip_sys1=skip_sys1, progress=progress)
            return rule.name, result, []
        except NovaEvaluationError as error:
            return rule.name, error.partial_result, error.causes

    if parallel and len(pending) > 1:
        with ThreadPoolExecutor(max_workers=min(10, len(pending))) as executor:
            completed = list(executor.map(finish, pending))
    else:
        completed = [finish(item) for item in pending]
    for name, result, errors in completed:
        results[name] = result
        causes.extend(errors)
    return [(rule, results[rule.name]) for rule in rules], causes
