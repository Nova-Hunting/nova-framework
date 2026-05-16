# Contributing to NOVA

Thanks for helping improve NOVA. This project is a beta security-adjacent engine, so changes should be easy to review, covered by focused tests, and careful about compatibility.

## Development Setup

```bash
git clone https://github.com/Nova-Hunting/nova-framework
cd nova-framework
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Quality Gates

Run these before opening a pull request:

```bash
python -m ruff check nova tests scripts test.py
python -m compileall -q nova tests scripts test.py
python -m pytest -q
python scripts/audit_dependencies.py
python scripts/check_secrets.py
python -m build
python -m twine check dist/*
python scripts/verify_artifacts.py
python scripts/smoke_wheel.py
git diff --check
```

For provider changes, add focused tests that do not require real API keys. Mock HTTP sessions or evaluator calls by default. Live-provider checks should be optional and should never commit secrets.

## Change Guidelines

- Keep behavioral changes scoped and document public API changes in `CHANGELOG.md`.
- Add regression tests for bug fixes, especially parser, matcher, condition, evaluator, and SDK behavior.
- Preserve existing public imports and environment variables unless the change is explicitly breaking.
- Do not add runtime dependencies for test, docs, lint, or release tooling; use extras in `setup.py`.
- Do not commit generated build artifacts, caches, local virtual environments, or real API keys.

## Security Issues

Do not open public issues for vulnerabilities. Follow `SECURITY.md` for private reporting.

## Pull Request Checklist

- [ ] Tests cover the changed behavior.
- [ ] `python -m ruff check nova tests scripts test.py` passes.
- [ ] `python -m pytest -q` passes.
- [ ] `python -m compileall -q nova tests scripts test.py` passes.
- [ ] `python scripts/audit_dependencies.py` passes.
- [ ] `python scripts/check_secrets.py` passes.
- [ ] `python -m build` succeeds.
- [ ] `python -m twine check dist/*` passes after building.
- [ ] `python scripts/verify_artifacts.py` passes after building.
- [ ] `python scripts/smoke_wheel.py` passes after building.
- [ ] `git diff --check` is clean.
- [ ] Documentation or changelog entries are updated when user-facing behavior changes.
