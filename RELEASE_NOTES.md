# Nova Hunting v0.3.0 Release Notes

## Highlights
- Added optional app attribution headers for OpenRouter: set `OPENROUTER_HTTP_REFERER` and `OPENROUTER_APP_TITLE` to send `HTTP-Referer` and `X-OpenRouter-Title` with OpenRouter requests, or pass `http_referer` / `app_title` to `OpenRouterEvaluator`.
- Fixed CLI startup so keyword-only scans and `novarun --help` do not import optional `transformers` or `torch` packages.
- Restructured the LLM evaluator module into a per-provider package (`nova/evaluators/llm/`) and moved the multi-rule file parser into `nova/core/rule_file.py`. All public import paths, including `nova.evaluators.llm` and `nova.core.parser`, are unchanged.
- Added `ARCHITECTURE.md`, a troubleshooting guide in `INSTALLATION.md`, and SDK quick-start and testing sections in `README.md`.
- Removed legacy pre-pytest manual test harnesses, the obsolete root `test.py` scratch script, and the unused `first.gif` asset, and updated the lint/compile gates accordingly.

## Compatibility
- No breaking changes. The public API, SDK behavior, CLI commands, `.nov` rule syntax, configuration format, and detection semantics are unchanged from v0.2.1.
- All supported LLM providers remain compatible: OpenAI, Anthropic, Azure OpenAI, Ollama, Groq, and OpenRouter.
- The public package version is `0.3.0`; `nova.__version__` and package metadata share a single source of truth in `nova/_version.py`.
- Supported Python versions are 3.10 and newer.
- Contributors: the local gates now lint `nova tests scripts` (the root `test.py` script no longer exists).
- Review `SECURITY.md` before reporting vulnerabilities or publishing downstream deployments.

For detailed changes, see `CHANGELOG.md`. For the v0.2.1 release notes, see the `CHANGELOG.md` `[0.2.1]` section.
