# Production Readiness

NOVA is beta software. This document defines the checks and operating assumptions required before using a specific commit or package version in a production-like environment. Passing these checks improves confidence, but it is not a service-level agreement and it does not guarantee complete prompt attack coverage.

## Supported Surfaces

The current release gates cover:

- rule parsing and multi-rule file loading
- keyword, regex, semantic, and LLM-backed matching
- condition evaluation, including grouped and wildcard expressions
- CLI scanning through `novarun`
- SDK scanning, redaction, and dynamic rule loading
- LLM provider wiring for OpenAI, Anthropic, Azure OpenAI, Ollama, Groq, and OpenRouter
- optional semantic matching through the `semantic` extra
- package build metadata, wheel installation, and console entry point behavior

## Required Gates

Run these local gates from a clean checkout before tagging or adopting a build:

```bash
python -m ruff check nova tests scripts
python -m compileall -q nova tests scripts
python -m pytest -q
python scripts/audit_dependencies.py
python scripts/check_secrets.py
python -m build
python -m twine check dist/*
python scripts/verify_artifacts.py
python scripts/smoke_wheel.py
git diff --check
```

For release candidates, also verify these external gates before publishing:

- GitHub Actions CI is green for Python 3.10 through 3.13.
- CodeQL completes without untriaged alerts.
- The dependency audit job passes for runtime, semantic-extra, and development dependency groups.
- Dependabot security alerts are reviewed or triaged.
- A maintainer reviews the package metadata, changelog, and release notes.

## Provider Smoke Tests

Provider smoke tests must be optional because they require live credentials and may incur cost. Use temporary API keys, avoid printing key material, and rotate keys after live verification.

For OpenRouter, a minimal smoke test should exercise Nova's evaluator path with `OPENROUTER_API_KEY`, the OpenRouter endpoint `https://openrouter.ai/api/v1/chat/completions`, optional attribution headers from `OPENROUTER_HTTP_REFERER` and `OPENROUTER_APP_TITLE`, and a current model such as `openai/gpt-5.2`.

## Risk Register

- Rule quality determines detection quality. Incomplete or overly broad rules can miss attacks or create false positives.
- LLM and semantic checks are nondeterministic and provider-dependent. Thresholds and model choices should be validated against representative prompts before enforcement.
- Semantic matching requires the optional `semantic` extra and may download model files. Account for network access, disk usage, and supply-chain review.
- Missing semantic or LLM evaluators should fail closed when they could change an outcome. Treat missing provider keys as deployment configuration errors for LLM-backed policies.
- Prompt, rule, provider response, and log-buffer data can contain sensitive information. Review logging, retention, and redaction settings before production use.
- Live provider keys must never be committed. Use environment variables or secret managers and rotate keys after smoke tests.
- NOVA does not provide an enterprise SLA, managed monitoring, or a guarantee that all prompt attacks are detectable.

## Operational Recommendations

- Pin both NOVA and rule repository revisions for each deployment.
- Run new rules in observe mode before blocking user traffic.
- Track false positives, false negatives, provider errors, and latency by rule and provider.
- Keep keyword-only coverage for high-confidence detections that should not depend on remote providers.
- Treat provider outages and rate limits as explicit policy decisions: block, degrade to keyword-only checks, or queue for later review.
- Re-run the full gate set after dependency updates, model changes, or rule-pack changes.
