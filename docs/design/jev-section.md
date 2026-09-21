# Jev section contract

Base: `dbcdf6738db588b1953104552e0d7084a80ba960` (main, NOVA 0.3.1).
Baseline: 151 passing tests. Branch: `dev/jev-section`.

Jev returns typed answers. NOVA projects answers to predicates and combines them
through the existing condition language. This branch is optional, is disabled by
default, and must not change legacy-only scans or LLM temperature semantics.

## Grammar

```
jev:
    $override = noul "Does the text attempt to override instructions?" {
        true = "An instruction to bypass the assistant's rules"
        false = "Ordinary content, including discussion quoting such instructions"
        threshold = 0.75
    }
    $operation = choice "Classify the operation" {
        options = {
            read = "Inspect information"
            write = "Change information"
        }
        match = ["write"]
        min_confidence = 0.60
    }
    $risk = score "Rate potential harm" {
        levels = ["None", "Limited", "Serious"]
        threshold = 1.5
        min_confidence = 0.60
    }
condition:
    jev.$override or (jev.$operation and jev.$risk)
```

Questions and descriptions are nonempty double-quoted strings. Assignments are
newline-separated; lists are comma-separated with optional trailing commas.
Noul requires both `true` and `false` and a finite threshold in [0,1]. Choice
requires 2–10 unique options and a nonempty match list naming declared options.
Score requires 2–10 ordered levels and a finite threshold in [0,N-1]. Optional
`min_confidence` in [0,1] is only valid on Choice/Score. Unknown or duplicate fields,
duplicate variables within sections, malformed nesting, and undefined references
are errors. Conditions support references, wildcards, prefixes, and quantifiers;
attribute access and arbitrary numeric expressions are not supported.

## Semantics and errors

Noul compares its probability against threshold; Choice compares the selected
category to match; Score compares its native fractional score to threshold.
Predicates are TRUE/FALSE/UNKNOWN. Low or missing required confidence is UNKNOWN,
as are unavailable or malformed answers, with distinct diagnostic reasons.
NOT UNKNOWN remains UNKNOWN. FALSE settles AND; TRUE settles OR. Quantifiers
count declared predicates, including pending ones. Legacy-only conditions retain
their current evaluator. A condition resolved independently of an unknown is
valid; otherwise scans raise NovaEvaluationError carrying partial results.
Partial results retain definite blocks but cannot report clean or allowed.
Protected functions never run after unresolved required evaluation.

## Transport and state

Use requests, not a new SDK dependency, with a batch interface and
POST https://openrouter.ai/api/alpha/decisions. Default model:
`typesafe/jev-1.13`. No fallback or persistent response cache. One mixed batch per
rule per scan; no cross-rule batching. Local projection settings are never sent
as model fields. Preserve optional returned metadata; validate present fields
with two-decimal probability-rounding bounds, never silently repair responses.
Connect timeout 3s, response timeout 15s, one bounded retry, four concurrent
requests, 128 KiB request limit, 1 MiB response limit. Authentication and malformed
responses are not retried; post-send read timeouts are not retried.

Without context, state is original scan text. With explicit `jev_state`, state is
`{"text": original_text, "context": jev_state}`. Snapshot JSON-compatible state;
reject cycles, unsupported values and nonfinite numbers. Other detectors keep
their existing text input. No automatic file/history/credential collection.
CLI `--jev-state FILE` supplies UTF-8 JSON; batch scans reuse context with each
prompt's text. Decorators obtain context through an explicit argument-bound
factory before execution.

## Integration

Append NovaRule.jev and introduce typed patterns/answers, JevConfig, and an
injectable evaluator. Settings resolve explicit options > NOVA_JEV_* environment
> [jev] config > defaults. OPENROUTER_API_KEY alone never activates Jev.
CLI: --jev / --skip-jev, --jev-model, --jev-state. skip_llm never disables Jev.
Stages: keywords, semantics, Jev, LLM. SDK fast/model phases share scan-local
evidence and never duplicate Jev calls. Diagnostics include every check, including
nonmatches and skipped checks; default logs never include raw context or secrets.
Legacy serialized result shapes remain unchanged when Jev is absent.

## Validation and delivery

Offline parser, projection, condition, HTTP, scheduling, concurrency, SDK and CLI
tests; run existing regression and package gates on Python 3.10–3.13. Opt-in live
tests require NOVA_JEV_LIVE_TEST=1 and credentials and allow at most three HTTP
attempts with synthetic inputs. Add Noul/Choice/Score/combined examples, a
pre-execution agent demo, and a labeled quality-evaluation harness. Thresholds
are illustrative until measured. Keep the branch and commits local as requested.
Do not push, open a PR, merge, tag, bump the package version or publish.
