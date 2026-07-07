import re
from pathlib import Path


SOURCE_ROOTS = [
    Path("nova"),
    Path("scripts"),
]

FORBIDDEN_PATTERNS = {
    "Python eval": re.compile(r"\beval\s*\("),
    "Python exec": re.compile(r"\bexec\s*\("),
    "shell=True subprocess": re.compile(r"\bshell\s*=\s*True\b"),
    "unsafe yaml.load": re.compile(r"\byaml\.load\s*\("),
    "pickle deserialization": re.compile(r"\bpickle\.loads?\s*\("),
    "marshal deserialization": re.compile(r"\bmarshal\.loads?\s*\("),
}


def iter_source_files():
    for root in SOURCE_ROOTS:
        for path in root.rglob("*.py"):
            yield path


def test_security_sensitive_unsafe_primitives_are_not_used():
    findings = []

    for path in iter_source_files():
        text = path.read_text(encoding="utf-8")
        for label, pattern in FORBIDDEN_PATTERNS.items():
            for match in pattern.finditer(text):
                line_number = text.count("\n", 0, match.start()) + 1
                findings.append(f"{path}:{line_number}: {label}")

    assert findings == []
