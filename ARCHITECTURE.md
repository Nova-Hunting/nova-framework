# NOVA Architecture

This document describes how the NOVA framework is organized and how a prompt flows through the detection pipeline. It is aimed at contributors; for usage documentation see [README.md](README.md), [INSTALLATION.md](INSTALLATION.md), and the [SDK guide](nova/sdk/README.md).

## Repository Layout

```
nova/
├── _version.py          # Single source of truth for the package version
├── core/                # Detection engine
│   ├── rules.py         # Rule data model (NovaRule, KeywordPattern, SemanticPattern, LLMPattern)
│   ├── parser.py        # Single-rule .nov parser and grammar validation (NovaParser)
│   ├── rule_file.py     # Multi-rule .nov file parser (NovaRuleFileParser)
│   ├── matcher.py       # Per-rule matching engine (NovaMatcher)
│   └── scanner.py       # Multi-rule scanning orchestration (NovaScanner)
├── evaluators/          # Pattern evaluation strategies
│   ├── base.py          # Abstract evaluator interfaces
│   ├── keywords.py      # Exact-string and regex matching
│   ├── semantics.py     # Embedding similarity (lazy-loads sentence-transformers)
│   ├── condition.py     # Restricted AST-based boolean condition evaluation
│   └── llm/             # LLM provider evaluators
│       ├── _shared.py   # Model env selection, TTL+LRU response cache, shared HTTP session
│       ├── _openai.py   # OpenAIEvaluator, OpenRouterEvaluator, AzureOpenAIEvaluator
│       ├── _anthropic.py# AnthropicEvaluator
│       ├── _groq.py     # GroqEvaluator (SDK and REST modes)
│       ├── _ollama.py   # OllamaEvaluator (local models)
│       └── _factory.py  # get_validated_evaluator() provider factory
├── sdk/                 # Application-embedding SDK
│   ├── nova.py          # Nova entry point: rule loading, scanning, policy enforcement
│   ├── policy.py        # NovaPolicy, PolicyRule, Action
│   ├── result.py        # ScanResult, RuleMatch
│   ├── redaction.py     # Redactor for matched keywords
│   ├── decorator.py     # @nova.protect / standalone protect and scan helpers
│   └── exceptions.py    # NovaBlockedError, NovaConfigError
├── utils/
│   ├── config.py        # NovaConfig INI config loading (provider, model, credentials)
│   ├── helpers.py       # Unicode normalization / homoglyph confusables handling
│   ├── logger.py        # Logger presets, JSON formatting, set_log_format()
│   └── log_buffer.py    # Ring-buffer log streaming helpers
└── novarun.py           # `novarun` CLI entry point
```

Public import paths are stable: everything importable from `nova`, `nova.core.*`, `nova.evaluators.*` (including `nova.evaluators.llm`), `nova.sdk`, and `nova.utils` before the module reorganization continues to work. Underscore-prefixed modules inside `nova/evaluators/llm/` are implementation details; import from `nova.evaluators.llm` directly.

## Detection Pipeline

A prompt scan flows through these stages:

1. **Rule loading** — `NovaRuleFileParser` (`nova/core/rule_file.py`) splits a `.nov` file into rule blocks and delegates each block to `NovaParser` (`nova/core/parser.py`), which validates grammar, section structure, variable naming, and condition references. Malformed rules fail closed with `NovaParserError`.
2. **Normalization** — scan inputs are normalized (`nova/utils/helpers.py`) with NFKC plus a homoglyph confusables map so zero-width and lookalike-character evasion cannot bypass keyword matching.
3. **Keyword evaluation** — `DefaultKeywordEvaluator` (`nova/evaluators/keywords.py`) runs exact and regex patterns. `/pattern/` is case-sensitive; `/pattern/i` is case-insensitive.
4. **Semantic evaluation** — `DefaultSemanticEvaluator` (`nova/evaluators/semantics.py`) computes embedding similarity against each `semantics:` pattern with its threshold. The ML stack (`sentence-transformers`) is imported lazily and only when a rule needs it; it is an optional `semantic` extra.
5. **LLM evaluation** — evaluators in `nova/evaluators/llm/` send the `llm:` pattern and the prompt to the configured provider and parse a structured JSON verdict. Responses are cached in a thread-safe TTL+LRU cache keyed by prompt, text, provider-qualified model, and temperature. All providers share one pooled `requests.Session`.
6. **Condition execution** — `evaluate_condition` (`nova/evaluators/condition.py`) evaluates the rule's boolean condition with a restricted AST evaluator (no Python `eval`). `NovaMatcher` schedules stages so cheap keyword checks short-circuit expensive semantic/LLM stages when they cannot change the outcome, and fails closed when a required evaluator is unavailable.
7. **Aggregation** — `NovaScanner` runs a prompt across many rules and reports matches; the SDK's `Nova` adds policy enforcement (allow / flag / block), redaction, warnings for degraded coverage, and the `@protect` decorator for wrapping application functions.

## Configuration Precedence

For provider, model, and credentials, the precedence is:

1. Explicit CLI flags (`--llm`, `--model`) or SDK constructor arguments
2. Environment variables (`OPENROUTER_API_KEY`, provider `*_LLM_MODEL` / `*_MODEL` overrides, `NOVA_LLM_MODEL` fallback)
3. Config file values (`novarun --config nova.ini`)
4. Provider defaults

When `--config` is passed explicitly, a missing or malformed file fails fast instead of silently falling back.

## Testing and Release Infrastructure

- `tests/` — pytest suite: parser/condition semantics (`test_condition.py`), scanner behavior (`test_scanner.py`), CLI smoke tests (`test_cli.py`), OpenRouter/provider selection (`test_openrouter.py`, `test_issue_22.py`), SDK engine (`test_sdk.py`) and SDK components (`test_sdk_components.py`), semantic matching (`test_semantics.py`), packaging/documentation consistency gates (`test_metadata.py`), and static security checks (`test_static_security.py`).
- `scripts/` — release gates: `check_secrets.py` (committed-secret scan), `audit_dependencies.py` (pip-audit by declared dependency group), `verify_artifacts.py` (sdist/wheel content checks), `smoke_wheel.py` (isolated wheel install + CLI smoke test).
- `.github/workflows/ci.yml` — whitespace, secret scan, test matrix (Python 3.10–3.13), package build validation, and dependency audit. `codeql.yml` provides static analysis.
- `RELEASE.md` — the release checklist; `PRODUCTION_READINESS.md` — supported surfaces and operational risks.

## Maintainability Notes

The 2026 cleanup split the two largest modules while preserving import paths: `nova/evaluators/llm.py` became the `nova/evaluators/llm/` package, and `NovaRuleFileParser` moved to `nova/core/rule_file.py` (re-exported from `nova.core.parser`). Remaining larger modules, in case future splits are wanted: `nova/core/parser.py` (~900 lines, single `NovaParser` class — split candidate: move condition-section validation into a helper module) and `nova/sdk/nova.py` (~870 lines — split candidate: extract rule-loading and fast-path scan scheduling). Neither exceeds the 1,000-line threshold today.
