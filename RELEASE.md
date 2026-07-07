# Release Checklist

Releases should favor correctness, clear changelogs, and reproducible artifacts over speed.

## Pre-Release

1. Confirm the working tree only contains intended release changes.
2. Update `CHANGELOG.md` with user-facing changes, compatibility notes, and migration guidance.
3. Confirm version metadata in `nova/_version.py`, package metadata, `CHANGELOG.md`, and `RELEASE_NOTES.md`.
4. Run the local gates:

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

5. Verify the built wheel metadata:

```bash
python - <<'PY'
from pathlib import Path
import re
requires = Path('nova_hunting.egg-info/requires.txt').read_text()
runtime = requires.split('\n\n[', 1)[0]
version = re.search(r'__version__ = "([^"]+)"', Path('nova/_version.py').read_text()).group(1)
assert 'pytest' not in runtime.lower()
assert 'ruff' not in runtime.lower()
assert 'pip-audit' not in runtime.lower()
assert 'twine' not in runtime.lower()
assert 'pyyaml' not in runtime.lower()
assert 'openai' not in runtime.lower()
assert 'anthropic' not in runtime.lower()
assert 'sentence-transformers' not in runtime.lower()
assert 'transformers' not in runtime.lower()
assert '[test]' in requires
assert '[lint]' in requires
assert '[semantic]' in requires
assert '[security]' in requires
assert '[release]' in requires
assert 'Requires-Python: >=3.10' in Path('nova_hunting.egg-info/PKG-INFO').read_text()
assert 'Project-URL: Security,' in Path('nova_hunting.egg-info/PKG-INFO').read_text()
assert 'Project-URL: Production Readiness,' in Path('nova_hunting.egg-info/PKG-INFO').read_text()
assert f'## [{version}]' in Path('CHANGELOG.md').read_text()
assert f'v{version}' in Path('RELEASE_NOTES.md').read_text().splitlines()[0]
print('release-metadata-ok')
PY
```

## GitHub Checks

Before publishing, require green status for:

- CI workflow
- CodeQL workflow
- package build job
- dependency audit job
- Dependabot security alerts reviewed or triaged

## Publishing

1. Create a signed or maintainer-approved release commit.
2. Tag the release with the package version.
3. Build fresh artifacts from the tag.
4. Publish the sdist and wheel.
5. Create a GitHub release with changelog highlights and known limitations.

## Post-Release

- Install the published package in a clean environment.
- Run a smoke test with keyword-only rules.
- Run optional provider smoke tests only with temporary API keys.
- Rotate any keys used for live release verification.
