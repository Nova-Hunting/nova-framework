"""Verify release artifacts contain the expected public and governance files."""

import re
import tarfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SDIST_REQUIRED_FILES = {
    "LICENCE",
    "README.md",
    "CHANGELOG.md",
    "RELEASE_NOTES.md",
    "INSTALLATION.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "RELEASE.md",
    "PRODUCTION_READINESS.md",
    "MANIFEST.in",
    "pyproject.toml",
    "setup.py",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/dependabot.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/codeql.yml",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    "scripts/audit_dependencies.py",
    "scripts/check_secrets.py",
    "scripts/smoke_wheel.py",
    "scripts/verify_artifacts.py",
    "tests/test_cli.py",
    "tests/test_condition.py",
    "tests/test_issue_22.py",
    "tests/test_metadata.py",
    "tests/test_openrouter.py",
    "tests/test_scanner.py",
    "tests/test_sdk.py",
    "tests/test_semantics.py",
    "tests/test_static_security.py",
    "nova/_version.py",
    "nova/utils/log_buffer.py",
}

WHEEL_REQUIRED_FILES = {
    "nova/_version.py",
    "nova/utils/log_buffer.py",
}

REQUIRED_PROJECT_URL_LABELS = {
    "Source",
    "Issues",
    "Security",
    "Changelog",
    "Production Readiness",
}


def get_version() -> str:
    version_text = (ROOT / "nova" / "_version.py").read_text(encoding="utf-8")
    match = re.search(r'__version__ = ["\']([^"\']+)["\']', version_text)
    if not match:
        raise RuntimeError("Unable to determine package version")
    return match.group(1)


def normalized_sdist_names(sdist: Path, version: str) -> set[str]:
    prefix = f"nova_hunting-{version}/"
    with tarfile.open(sdist, "r:gz") as archive:
        names = set()
        for member in archive.getmembers():
            if not member.isfile() or not member.name.startswith(prefix):
                continue
            names.add(member.name.removeprefix(prefix))
        return names


def wheel_names(wheel: Path) -> set[str]:
    with zipfile.ZipFile(wheel) as archive:
        return set(archive.namelist())


def wheel_metadata(wheel: Path, version: str) -> str:
    metadata_path = f"nova_hunting-{version}.dist-info/METADATA"
    with zipfile.ZipFile(wheel) as archive:
        return archive.read(metadata_path).decode("utf-8")


def require_subset(required: set[str], actual: set[str], artifact: Path) -> None:
    missing = sorted(required - actual)
    if missing:
        missing_list = "\n".join(f"- {name}" for name in missing)
        raise SystemExit(f"{artifact} is missing required files:\n{missing_list}")


def main() -> None:
    version = get_version()
    sdist = ROOT / "dist" / f"nova_hunting-{version}.tar.gz"
    wheel = ROOT / "dist" / f"nova_hunting-{version}-py3-none-any.whl"

    if not sdist.is_file():
        raise SystemExit(f"Built sdist not found: {sdist}")
    if not wheel.is_file():
        raise SystemExit(f"Built wheel not found: {wheel}")

    require_subset(SDIST_REQUIRED_FILES, normalized_sdist_names(sdist, version), sdist)
    require_subset(WHEEL_REQUIRED_FILES, wheel_names(wheel), wheel)

    metadata = wheel_metadata(wheel, version)
    for label in REQUIRED_PROJECT_URL_LABELS:
        if f"Project-URL: {label}," not in metadata:
            raise SystemExit(f"{wheel} is missing Project-URL metadata for {label}")

    print("release-artifacts-ok")


if __name__ == "__main__":
    main()
