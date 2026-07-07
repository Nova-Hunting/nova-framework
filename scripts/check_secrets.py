"""Scan repository files for committed API-key shaped secrets."""

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SECRET_PATTERNS = {
    "OpenRouter API key": re.compile(r"\bsk-or-v1-[A-Za-z0-9_-]{20,}\b"),
    "OpenAI-style API key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "Groq API key": re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b"),
}


def candidate_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        ROOT / name
        for name in result.stdout.splitlines()
        if (ROOT / name).is_file()
    ]


def read_text(path: Path) -> str | None:
    data = path.read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def main() -> None:
    findings = []
    for path in candidate_paths():
        text = read_text(path)
        if text is None:
            continue
        relative = path.relative_to(ROOT)
        for label, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(text):
                line_number = text.count("\n", 0, match.start()) + 1
                findings.append(f"{relative}:{line_number}: possible {label}")

    if findings:
        finding_text = "\n".join(findings)
        raise SystemExit(f"Secret scan failed:\n{finding_text}")

    print("secret-scan-ok")


if __name__ == "__main__":
    main()
