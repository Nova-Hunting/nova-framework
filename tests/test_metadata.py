from importlib.metadata import metadata, requires, version
from pathlib import Path

import nova
import yaml
from nova._version import __version__
from scripts.audit_dependencies import dedupe, parse_requires


def test_public_version_matches_package_metadata():
    assert nova.__version__ == version("nova-hunting")


def test_release_docs_reference_current_version():
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    release_notes = Path("RELEASE_NOTES.md").read_text(encoding="utf-8")

    assert f"## [{__version__}]" in changelog
    assert f"v{__version__}" in release_notes.splitlines()[0]
    assert "OPENROUTER_HTTP_REFERER" in changelog
    assert "OPENROUTER_APP_TITLE" in changelog
    assert "optional `transformers` or `torch` packages" in changelog
    assert "optional app attribution headers" in release_notes
    assert "optional `transformers` or `torch` packages" in release_notes


def test_tooling_dependencies_are_not_runtime_requirements():
    package_requires = requires("nova-hunting") or []
    runtime_requires = [
        requirement for requirement in package_requires
        if "extra ==" not in requirement
    ]

    assert not any("pytest" in requirement.lower() for requirement in runtime_requires)
    assert not any("ruff" in requirement.lower() for requirement in runtime_requires)
    assert not any("pip-audit" in requirement.lower() for requirement in runtime_requires)
    assert not any("twine" in requirement.lower() for requirement in runtime_requires)
    assert not any("pyyaml" in requirement.lower() for requirement in runtime_requires)
    assert not any("openai" in requirement.lower() for requirement in runtime_requires)
    assert not any("anthropic" in requirement.lower() for requirement in runtime_requires)
    assert not any("sentence-transformers" in requirement.lower() for requirement in runtime_requires)
    assert not any("transformers" in requirement.lower() for requirement in runtime_requires)
    assert any(
        "pyyaml" in requirement.lower() and 'extra == "test"' in requirement
        for requirement in package_requires
    )
    assert any(
        "twine" in requirement.lower() and 'extra == "release"' in requirement
        for requirement in package_requires
    )
    assert any(
        "sentence-transformers" in requirement.lower() and 'extra == "semantic"' in requirement
        for requirement in package_requires
    )
    assert any(
        "pip-audit" in requirement.lower() and 'extra == "security"' in requirement
        for requirement in package_requires
    )


def test_python_requires_matches_supported_dependency_floor():
    package_metadata = metadata("nova-hunting")
    assert package_metadata["Requires-Python"] == ">=3.10"


def test_source_headers_do_not_claim_stale_version():
    source_paths = list(Path("nova").rglob("*.py")) + list(Path("tests").glob("*.py"))
    stale_header = "Version: " + "1.0.0"

    for path in source_paths:
        assert stale_header not in path.read_text(encoding="utf-8")


def test_public_docs_describe_openrouter_and_current_dev_gates():
    readme = Path("README.md").read_text(encoding="utf-8")
    installation = Path("INSTALLATION.md").read_text(encoding="utf-8")
    sdk_readme = Path("nova/sdk/README.md").read_text(encoding="utf-8")

    assert "--llm openrouter" in readme
    assert "--config nova.ini" in readme
    assert "[api_keys]" in readme
    assert "missing or malformed" in readme
    assert "PRODUCTION_READINESS.md" in readme
    assert "OPENROUTER_LLM_MODEL" in installation
    assert "OPENROUTER_HTTP_REFERER" in readme
    assert "OPENROUTER_APP_TITLE" in installation
    assert "GROQ_API_KEY" in installation
    assert "AZURE_OPENAI_ENDPOINT" in installation
    assert "GROQ_MODEL" in installation
    assert "--config nova.ini" in installation
    assert "[api_keys]" in installation
    assert "missing or malformed" in installation
    assert "OLLAMA_HOST" in readme
    assert 'llm_provider="openrouter"' in sdk_readme
    assert "X-OpenRouter-Title" in sdk_readme
    assert "python -m ruff check nova tests scripts" in installation
    assert "python -m compileall -q nova tests scripts" in installation
    assert "python scripts/audit_dependencies.py" in installation
    assert "python scripts/check_secrets.py" in installation
    assert "python scripts/verify_artifacts.py" in installation
    assert 'pip install "nova-hunting[semantic]"' in installation


def test_package_metadata_has_trust_and_support_links():
    package_metadata = metadata("nova-hunting")
    project_urls = package_metadata.get_all("Project-URL") or []

    for label in [
        "Source",
        "Issues",
        "Security",
        "Changelog",
        "Production Readiness",
    ]:
        assert any(url.startswith(f"{label},") for url in project_urls)


def test_release_artifact_manifest_and_verifier_cover_governance_files():
    manifest = Path("MANIFEST.in").read_text(encoding="utf-8")
    verifier = Path("scripts/verify_artifacts.py").read_text(encoding="utf-8")

    for expected in [
        "SECURITY.md",
        "CONTRIBUTING.md",
        "PRODUCTION_READINESS.md",
        "RELEASE.md",
        "CHANGELOG.md",
        "RELEASE_NOTES.md",
        ".github/workflows/ci.yml",
        ".github/workflows/codeql.yml",
        ".github/dependabot.yml",
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
    ]:
        assert expected in manifest
        assert expected in verifier


def test_wheel_smoke_exercises_installed_package_and_cli():
    smoke = Path("scripts/smoke_wheel.py").read_text(encoding="utf-8")

    assert "--no-deps" not in smoke
    assert "import nova" in smoke
    assert "NovaMatcher" in smoke
    assert "NovaParser" in smoke
    assert '"nova.novarun"' in smoke
    assert "--help" in smoke
    assert "openrouter" in smoke
    assert "MATCHED" in smoke


def test_production_readiness_document_covers_operational_risks_and_gates():
    readiness = Path("PRODUCTION_READINESS.md").read_text(encoding="utf-8")

    for expected in [
        "NOVA is beta software",
        "Supported Surfaces",
        "Required Gates",
        "python -m ruff check nova tests scripts",
        "python scripts/audit_dependencies.py",
        "python scripts/check_secrets.py",
        "python scripts/verify_artifacts.py",
        "python scripts/smoke_wheel.py",
        "GitHub Actions CI",
        "CodeQL",
        "OpenRouter",
        "OPENROUTER_HTTP_REFERER",
        "OPENROUTER_APP_TITLE",
        "openai/gpt-5.2",
        "semantic",
        "fail closed",
        "rotate keys",
        "Risk Register",
        "Operational Recommendations",
    ]:
        assert expected in readiness


def test_pull_request_template_lists_required_local_gates():
    template = Path(".github/PULL_REQUEST_TEMPLATE.md").read_text(encoding="utf-8")

    assert "python -m ruff check nova tests scripts" in template
    assert "python -m compileall -q nova tests scripts" in template
    assert "python -m pytest -q" in template
    assert "python scripts/audit_dependencies.py" in template
    assert "python scripts/check_secrets.py" in template
    assert "python -m build" in template
    assert "python -m twine check dist/*" in template
    assert "python scripts/verify_artifacts.py" in template
    assert "python scripts/smoke_wheel.py" in template
    assert "git diff --check" in template


def test_ci_workflow_covers_supported_versions_and_release_gates():
    workflow = yaml.safe_load(Path(".github/workflows/ci.yml").read_text(encoding="utf-8"))
    jobs = workflow["jobs"]

    whitespace_runs = "\n".join(
        step.get("run", "")
        for step in jobs["whitespace"]["steps"]
    )
    assert jobs["whitespace"]["steps"][0]["with"]["fetch-depth"] == 0
    assert "git diff --check" in whitespace_runs
    assert "git diff-tree --check" in whitespace_runs

    secret_scan_runs = "\n".join(
        step.get("run", "")
        for step in jobs["secret-scan"]["steps"]
    )
    assert "python scripts/check_secrets.py" in secret_scan_runs

    assert jobs["test"]["strategy"]["matrix"]["python-version"] == ["3.10", "3.11", "3.12", "3.13"]

    test_runs = "\n".join(
        step.get("run", "")
        for step in jobs["test"]["steps"]
    )
    assert "python -m ruff check nova tests scripts" in test_runs
    assert "python -m pytest -q" in test_runs
    assert "python -m compileall -q nova tests scripts" in test_runs

    package_runs = "\n".join(
        step.get("run", "")
        for step in jobs["package"]["steps"]
    )
    assert "python -m build" in package_runs
    assert "python -m twine check dist/*" in package_runs
    assert "python scripts/verify_artifacts.py" in package_runs
    assert "python scripts/smoke_wheel.py" in package_runs

    audit_runs = "\n".join(
        step.get("run", "")
        for step in jobs["dependency-audit"]["steps"]
    )
    assert 'python -m pip install "pip-audit~=2.10.0"' in audit_runs
    assert "python scripts/audit_dependencies.py" in audit_runs
    assert 'python -m pip install -e ".[security]"' not in audit_runs
    assert "python -m pip_audit --local" not in audit_runs


def test_dependency_audit_script_parses_declared_groups(tmp_path):
    requires_file = tmp_path / "requires.txt"
    requires_file.write_text(
        """
requests~=2.34.2
colorama~=0.4.6

[semantic:python_version >= "3.10"]
sentence-transformers~=5.5.0

[dev]
pytest~=9.0.3
pytest~=9.0.3
""",
        encoding="utf-8",
    )

    sections = parse_requires(requires_file)

    assert sections["runtime"] == ["requests~=2.34.2", "colorama~=0.4.6"]
    assert sections["semantic"] == ["sentence-transformers~=5.5.0"]
    assert dedupe(sections["dev"]) == ["pytest~=9.0.3"]
