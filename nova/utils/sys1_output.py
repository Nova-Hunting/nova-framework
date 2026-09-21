"""Readable terminal summaries of Sys1 evidence, without dumping scan input."""

import textwrap


def format_sys1_output(details, index, elapsed_ms, config, verbose=False, causes=()):
    results = details.get("detailed_results", {})
    matched = sum(bool(result.get("matched")) for result in results.values())
    complete = details.get("evaluation_complete", False)
    duration = f"{elapsed_ms / 1000:.2f} s" if elapsed_ms >= 1000 else f"{elapsed_ms:.0f} ms"
    summary = f"Prompt {index + 1}  |  {matched}/{len(results)} rules matched  |  {duration}"
    if not complete:
        summary += "  |  INCOMPLETE"
    lines = ["", summary]
    if verbose:
        lines.append(f"Model: {config.model}  |  Provider: {config.provider}")

    def detail(label, value):
        lines.append(textwrap.fill(f"{label}: {value}", width=100,
                                   initial_indent="    ", subsequent_indent="      ",
                                   break_long_words=False, break_on_hyphens=False))

    for name, result in results.items():
        status = "MATCH" if result.get("matched") else "NO MATCH"
        if not result.get("evaluation_complete", True):
            status = "INCOMPLETE"
        lines.extend(["", f"{status}  {name}"])
        entries = result.get("sys1_results", {})
        skipped = 0
        for variable, entry in entries.items():
            if entry.get("status") == "skipped" and not verbose:
                skipped += 1
                continue
            kind = entry["primitive"]
            answer, settings = entry.get("answer") or {}, entry.get("settings", {})
            predicate = {"true": "MATCH", "false": "NO MATCH", "unknown": "UNKNOWN"}[entry.get("predicate", "unknown")]
            if entry.get("status") == "skipped":
                predicate = "SKIPPED"
            value = answer.get({"noul": "noul", "choice": "choice", "score": "score"}[kind])
            parts = []
            if "threshold" in settings:
                parts.append(f"threshold {settings['threshold']}")
            if answer.get("confidence") is not None:
                confidence = f"confidence {answer['confidence']}"
                if settings.get("min_confidence") is not None:
                    confidence += f" (min {settings['min_confidence']})"
                parts.append(confidence)
            elif settings.get("min_confidence") is not None and answer:
                parts.append(f"confidence missing (min {settings['min_confidence']})")
            evidence = "  |  ".join(parts)
            displayed_value = str(value) if value is not None else "not evaluated" if predicate == "SKIPPED" else "unavailable"
            lines.append(f"  {kind.title()} {variable}: {displayed_value}  |  {predicate}" + (f"  |  {evidence}" if evidence else ""))
            if entry.get("reason"):
                detail("Reason", entry["reason"].replace("_", " "))
            if verbose:
                if "match" in settings:
                    detail("Match categories", ", ".join(settings["match"]))
                if answer.get("probabilities") is not None:
                    detail("Probabilities", ", ".join(f"{key}={value}" for key, value in answer["probabilities"].items()))
                if answer.get("legend") is not None:
                    detail("Levels", "; ".join(f"{key}={value}" for key, value in answer["legend"].items()))
        if skipped:
            lines.append(f"  {skipped} Sys1 check{'s' if skipped != 1 else ''} skipped")
        debug = result.get("debug", {})
        if verbose:
            detail("Condition", f"{debug.get('condition', '')} -> {debug.get('condition_result', 'unknown')}")
            for section in ("keywords", "semantics", "llm"):
                matches = result.get(f"matching_{section}", {})
                if matches:
                    detail(f"Matched {section}", ", ".join(matches))
            for batch in result.get("sys1_batches", []):
                metadata = [f"{key}={batch[key]}" for key in ("id", "model", "provider") if batch.get(key) is not None]
                if batch.get("request_count") is not None:
                    metadata.append(f"HTTP attempts={batch['request_count']}")
                if metadata:
                    detail("Request", "  |  ".join(metadata))
                if batch.get("usage"):
                    detail("Usage", ", ".join(f"{key}={value}" for key, value in batch["usage"].items()))
        # Sys1 reasons are already shown with their variables; retain other stage warnings.
        for warning in debug.get("evaluation_warnings", []):
            if not warning.startswith("sys1."):
                detail("Warning", warning)
    if not results and causes:
        lines.append("  Reason: " + ", ".join(sorted(set(causes))))
    return "\n".join(lines) + "\n"
