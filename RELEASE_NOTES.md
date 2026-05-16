# Nova Hunting v0.2.1 Release Notes

## Highlights
- Added OpenRouter support through `--llm openrouter`, `llm_type="openrouter"`, and `OPENROUTER_API_KEY`.
- Fixed issue #22 compatibility regressions around condition helpers, logger exports, log buffering, and provider-specific model overrides.
- Hardened condition evaluation by replacing Python `eval()` with a restricted AST evaluator.
- Improved matcher correctness for quantified wildcard conditions and unavailable semantic/LLM evaluators.
- Tightened LLM response caching so provider context and temperature are part of the cache key.
- Tightened SDK and scanner loading paths so missing, malformed, or duplicate rules fail closed by default and scanner LLM provider selection works outside the CLI.
- Removed shared matcher mutation from the SDK fast LLM scan path, improving safety for concurrent request handling.
- Fixed dynamic SDK LLM rule additions so configured providers and models are honored consistently.
- Aligned SDK matching with core scanner Unicode normalization and added normalized redaction fallback for keyword matches.
- Made SDK keyword redaction follow keyword matcher semantics for literal, regex, and case-sensitive patterns.
- Accepted leading header comments in single-rule parsing and CLI rule loading.
- Made multi-rule CLI loading use the shared rule-file parser and fail closed on malformed or duplicate rules.
- Made CLI fail-closed semantic/LLM warnings visible without requiring verbose mode.
- Rejected unknown rule sections during parsing so section-name typos cannot silently weaken rules.
- Rejected duplicate variable names across `keywords`, `semantics`, and `llm` to avoid ambiguous standalone references and cross-section wildcard collisions.
- Rejected malformed rule variable names during parsing to prevent ambiguous condition behavior.
- Accepted `#` whole-line comments consistently inside rule sections.
- Anchored multi-rule boundary detection so metadata or prompt text containing `rule` does not split files incorrectly.
- Fixed matcher scheduling for bare section quantifiers such as `any of keywords`, `all of semantics`, and `2 of llm`.
- Fixed short-circuit analysis so bare semantic and LLM quantifiers are not skipped before their evaluators run.
- Fixed condition variable replacement so similarly named variables such as `$a` and `$aa` cannot corrupt each other during evaluation.
- Rejected unsupported raw standalone wildcards like `$risk*` so they cannot be mistaken for shorter variable names.
- Fixed matcher and parser variable-reference analysis so section prefix wildcards like `keywords.$risk*` are not also treated as shorter direct variables.
- Fixed explicit `skip_llm=True` matching so skipped LLM values fail closed when they could change the condition outcome.
- Fixed matcher evaluator error handling so keyword, semantic, and LLM evaluator failures fail closed instead of turning into `False` values that can satisfy negated conditions.
- Surfaced fail-closed semantic/LLM warnings on SDK `ScanResult` objects so production callers can distinguish clean scans from degraded-coverage scans.
- Populated SDK `RuleMatch.matched_patterns` and preserved LLM match evidence, source files, and matched pattern names in `ScanResult.to_dict()` output.
- Surfaced SDK parallel LLM worker exceptions as rule warnings instead of silently dropping those degraded evaluations.
- Normalized SDK policy string actions consistently across defaults, severity mappings, setters, and `PolicyRule` objects.
- Added clear SDK policy config validation and string action shorthand, for example `{"RuleName": "block"}`.
- Fixed `novarun --config` so provider, model, credentials, Azure endpoints, and Ollama hosts are honored with CLI and environment precedence preserved.
- Made explicit `--config` loading fail fast when files are missing or malformed instead of silently falling back to defaults.
- Made `NovaConfig.save()` report write failures as exceptions so callers can fail closed.
- Added CI, static correctness checks, package build validation, CodeQL, Dependabot, security policy, contributor guidance, and release checklist.
- Added dependency-audit CI coverage with `pip-audit` and moved semantic ML dependencies behind the optional `semantic` extra.
- Added a deterministic dependency-audit script that audits declared runtime, semantic, and development dependency groups without scanning unrelated local or runner packages.

## Compatibility
- The public package version is `0.2.1`; `nova.__version__` and package metadata now share a single source of truth.
- Supported Python versions are 3.10 and newer, matching the audited dependency floor.
- Runtime dependencies no longer include test, lint, documentation, release, security-audit, semantic ML tooling, YAML test tooling, or provider SDK packages. Use `pip install "nova-hunting[semantic]"` for semantic rules and `pip install -e ".[dev]"` for development.
- NOVA remains beta software. Review `SECURITY.md` before reporting vulnerabilities or publishing downstream deployments.

For detailed changes, see `CHANGELOG.md`.
