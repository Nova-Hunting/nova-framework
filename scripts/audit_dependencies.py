"""Audit declared NOVA dependency groups without auditing ambient packages."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EGG_REQUIRES = ROOT / "nova_hunting.egg-info" / "requires.txt"


def run_command(args: list[str]) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def refresh_package_metadata() -> None:
    run_command([sys.executable, "setup.py", "egg_info"])


def parse_requires(path: Path) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"runtime": []}
    current_section = "runtime"

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].split(":", 1)[0]
            sections.setdefault(current_section, [])
            continue
        if line.startswith("#"):
            continue
        sections.setdefault(current_section, []).append(line)

    return sections


def write_requirements_file(name: str, requirements: list[str]) -> Path:
    if not requirements:
        raise RuntimeError(f"No requirements found for audit target: {name}")

    temp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f"nova-{name}-",
        suffix=".txt",
        delete=False,
    )
    with temp:
        temp.write("\n".join(requirements))
        temp.write("\n")
    return Path(temp.name)


def audit_requirements(name: str, requirements: list[str]) -> None:
    requirements_file = write_requirements_file(name, requirements)
    try:
        run_command([sys.executable, "-m", "pip_audit", "-r", str(requirements_file)])
    finally:
        requirements_file.unlink(missing_ok=True)
    print(f"{name}-dependency-audit-ok")


def dedupe(requirements: list[str]) -> list[str]:
    seen = set()
    unique_requirements = []
    for requirement in requirements:
        if requirement in seen:
            continue
        seen.add(requirement)
        unique_requirements.append(requirement)
    return unique_requirements


def main() -> None:
    refresh_package_metadata()
    sections = parse_requires(EGG_REQUIRES)

    runtime = sections.get("runtime", [])
    semantic = dedupe(runtime + sections.get("semantic", []))
    dev = dedupe(runtime + sections.get("dev", []))

    audit_requirements("runtime", runtime)
    audit_requirements("semantic", semantic)
    audit_requirements("dev", dev)
    print("dependency-audit-ok")


if __name__ == "__main__":
    main()
