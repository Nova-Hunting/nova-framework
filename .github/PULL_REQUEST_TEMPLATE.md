## Summary

Describe the change and why it is needed.

## Validation

- [ ] `python -m ruff check nova tests scripts test.py`
- [ ] `python -m compileall -q nova tests scripts test.py`
- [ ] `python -m pytest -q`
- [ ] `python scripts/audit_dependencies.py`
- [ ] `python scripts/check_secrets.py`
- [ ] `python -m build`
- [ ] `python -m twine check dist/*`
- [ ] `python scripts/verify_artifacts.py`
- [ ] `python scripts/smoke_wheel.py`
- [ ] `git diff --check`

## Compatibility

- [ ] Public API changes are documented.
- [ ] New runtime dependencies are justified.
- [ ] New optional dependencies are assigned to the right extra.
- [ ] Provider changes do not require real API keys in tests.
- [ ] Security-sensitive behavior has been reviewed.
