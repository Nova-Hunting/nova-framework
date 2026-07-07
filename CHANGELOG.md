# NOVA Framework Changelog

## [0.3.0] - 2026-07-07

### Added
- Added optional OpenRouter app attribution headers through `OPENROUTER_HTTP_REFERER` and `OPENROUTER_APP_TITLE` environment variables, or the `http_referer` and `app_title` `OpenRouterEvaluator` constructor arguments.
- Added `ARCHITECTURE.md` describing the repository layout, detection pipeline, and configuration precedence.
- Added a troubleshooting guide to `INSTALLATION.md`.
- Added SDK quick-start and testing sections to `README.md`.

### Fixed
- Fixed CLI startup so keyword-only scans and `novarun --help` do not import optional `transformers` or `torch` packages.

### Changed
- Restructured `nova/evaluators/llm.py` (1,372 lines) into the `nova/evaluators/llm/` package with per-provider modules and shared cache/session infrastructure. All public imports from `nova.evaluators.llm` are unchanged.
- Moved `NovaRuleFileParser` into `nova/core/rule_file.py`; it remains importable from `nova.core.parser`.
- Split `tests/test_sdk.py` into `tests/test_sdk.py` (engine, decorator, async, debug) and `tests/test_sdk_components.py` (policy, scan results, redaction).

### Removed
- Removed legacy manual test harnesses that predated the pytest suite: `tests/novatest.py`, `tests/novatester.py`, `tests/testerror.py`, `tests/validateerror.py`, and `tests/prompts_testing.txt`.
- Removed the obsolete root `test.py` scratch script (it referenced a nonexistent rules path and private matcher APIs) and dropped it from the lint/compile gates in CI and documentation.
- Removed the unused `first.gif` asset.

## [0.2.1] - 2026-05-15

### Added
- Added `OpenRouterEvaluator` for OpenRouter's OpenAI-compatible chat completions API.
- Added `llm_type="openrouter"` and `--llm openrouter` support.
- Added `NovaScanner` LLM provider selection and injected evaluator reuse.
- Added `OPENROUTER_API_KEY`, `OPENROUTER_LLM_MODEL`, and `OPENROUTER_MODEL` environment variable support.
- Added CLI smoke tests for `novarun` help output, OpenRouter argument support, and keyword-only scans.
- Added regression tests for quantified condition wildcards, condition-change helper behavior, matcher short-circuiting, and package metadata.
- Added GitHub Actions CI for Python 3.10-3.13, pytest, Ruff correctness checks, bytecode compilation, and package builds.
- Added Twine package metadata validation for release builds.
- Added isolated wheel install smoke testing for built package artifacts.
- Added CodeQL and Dependabot configuration.
- Added `security` and `semantic` package extras, plus CI dependency audits with `pip-audit`.
- Added `scripts/audit_dependencies.py` to audit runtime, semantic, and development dependency groups from package metadata without auditing ambient runner packages.
- Added `SECURITY.md`, `CONTRIBUTING.md`, `RELEASE.md`, pull request template, and issue templates.
- Added SDK `ScanResult.warnings`, `ScanResult.rule_warnings`, and `ScanResult.has_warnings` so callers can detect degraded semantic/LLM coverage even when no rules match.

### Fixed
- Restored working `can_llm_change_outcome()` and `can_semantics_change_outcome()` behavior after upstream placeholder stubs.
- Fixed `N of keywords.*`, `N of semantics.*`, and `N of llm.*` condition evaluation order.
- Fixed `all of ...` and quantified prefix wildcard conditions across parser, matcher, and condition helpers.
- Fixed matcher short-circuiting so cross-stage quantified wildcards cannot match before later stages run.
- Fixed rules that require unavailable semantic or LLM evaluation to fail closed when that stage could affect the outcome.
- Fixed LLM response cache keys to include provider context and temperature.
- Fixed regex case sensitivity: `/pattern/` is case-sensitive and `/pattern/i` is case-insensitive.
- Restored `nova.utils.log_buffer` with ring-buffer log streaming helpers.
- Restored logger format presets, JSON formatting, and `set_log_format()`.
- Restored provider-specific LLM model environment overrides such as `OPENAI_LLM_MODEL` and `ANTHROPIC_LLM_MODEL`.
- Fixed `.gitignore` so `tests/` is no longer ignored.
- Fixed README and installation quick-start CLI flags.
- Fixed README license link.
- Fixed public `nova.__version__` to match package metadata from a single source of truth.
- Fixed advertised Python support to require Python 3.10+, matching the audited runtime dependency floor.
- Fixed SDK rule loading to fail closed on missing, malformed, or duplicate rule files unless `ignore_invalid_rules=True`.
- Fixed SDK directory loading to discover nested `.nov` files.
- Fixed `NovaScanner` duplicate rule handling so constructor and batch additions cannot overwrite or partially mutate scanner state.
- Fixed SDK fast-path LLM scans so they no longer mutate shared matcher evaluator state during concurrent scans.
- Fixed SDK dynamic LLM rule additions to use the configured provider/model instead of falling back to matcher defaults.
- Fixed SDK scans to apply Unicode normalization before matching, closing a homoglyph and zero-width keyword evasion gap.
- Fixed SDK keyword redaction to fall back to normalized text when a match only exists after Unicode normalization.
- Fixed SDK keyword redaction to honor literal, regex, and case-sensitive keyword semantics.
- Fixed single-rule parser and CLI loading so leading header comments before `rule` declarations are accepted.
- Fixed multi-rule CLI loading to use the shared rule-file parser and fail closed on malformed or duplicate rules.
- Fixed CLI output so fail-closed semantic/LLM evaluation warnings are visible even without verbose mode.
- Fixed parser handling for unknown rule sections so typos now fail closed instead of being silently ignored.
- Fixed parser validation so variable names must be unique across `keywords`, `semantics`, and `llm`, preventing ambiguous standalone references and cross-section wildcard collisions.
- Fixed parser validation so malformed variable names are rejected before they can produce ambiguous condition behavior.
- Fixed parser comment handling so `#` whole-line comments are accepted consistently inside rule sections.
- Fixed multi-rule boundary detection so `rule` inside metadata or prompts is not mistaken for a rule declaration.
- Fixed matcher scheduling for bare section quantifiers such as `any of keywords`, `all of semantics`, and `2 of llm`.
- Fixed short-circuit analysis so bare semantic and LLM quantifiers are not skipped before their evaluators run.
- Fixed condition variable replacement so similarly named variables such as `$a` and `$aa` cannot corrupt each other during evaluation.
- Fixed parser validation so unsupported raw standalone wildcards like `$risk*` are rejected instead of being mistaken for shorter variable names.
- Fixed matcher and parser variable-reference analysis so section prefix wildcards like `keywords.$risk*` are not also treated as shorter direct variables.
- Fixed explicit `skip_llm=True` matching so skipped LLM values fail closed when they could change the condition outcome.
- Fixed matcher evaluator error handling so keyword, semantic, and LLM evaluator failures fail closed instead of turning into `False` values that can satisfy negated conditions.
- Fixed high-level SDK scans so fail-closed matcher warnings are surfaced instead of being hidden when a degraded rule does not match.
- Fixed SDK `RuleMatch.matched_patterns` population and `ScanResult.to_dict()` so serialized matches preserve LLM match evidence, source files, and matched pattern names.
- Fixed SDK parallel LLM evaluation so worker exceptions are surfaced as rule warnings instead of being silently swallowed.
- Fixed SDK policy action normalization so string defaults, severity actions, setters, and `PolicyRule` objects behave like `Action` enum values.
- Fixed SDK policy config validation so malformed policy shapes fail with clear errors, and added string action shorthand such as `{"RuleName": "block"}`.
- Fixed configuration loading so `GROQ_API_KEY` is captured consistently with other supported LLM provider credentials.
- Fixed `novarun --config` so provider, model, credentials, Azure endpoints, and Ollama hosts are applied while preserving CLI and environment precedence.
- Fixed explicit config loading so missing or malformed `--config` files fail fast instead of silently falling back to defaults.
- Fixed `NovaConfig.save()` so write failures raise an exception instead of being hidden behind a printed message.

### Changed
- Moved test, lint, documentation, security-audit, semantic-model, provider-SDK example, and release tooling out of default runtime dependencies.
- Removed unused `pyyaml`, `openai`, and `anthropic` packages from the standard install footprint; provider evaluation uses Nova's HTTP evaluators.
- Updated default `requests` and optional semantic stack dependency pins to versions that pass a clean `pip-audit` check.
- Removed Python 3.8 and 3.9 from the CI matrix because audited runtime dependencies no longer support them.
- Removed the deprecated license classifier while keeping MIT license metadata.
- Hardened condition evaluation with a restricted AST evaluator instead of Python `eval()`.
- Broadened the Ruff gate to cover the maintained source, test, and script surface.

### Notes
- Live provider checks should use temporary API keys and should never commit secrets.
- NOVA remains beta software; review `SECURITY.md` and `RELEASE.md` before publishing production releases.

## [0.1.4] - 2025-04-13

### Fixed
- Reduced tokenizer warning noise from the transformers stack.
- Updated warning handling around tokenization cleanup.

## [0.1.2] - 2024-12-18

### Added
- Renamed the package to `nova-hunting`.
- Added LLM evaluator sharing across scanner runs.
- Added lazy initialization of LLM resources.
- Added Groq Cloud evaluator support.

### Fixed
- Fixed invalid regex pattern validation in the parser.
- Added error handling for malformed regex patterns.
