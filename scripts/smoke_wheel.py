"""Smoke-test the built wheel artifact in an isolated virtual environment."""

import os
import re
import subprocess
import tempfile
import textwrap
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def get_version() -> str:
    version_text = (ROOT / "nova" / "_version.py").read_text(encoding="utf-8")
    match = re.search(r'__version__ = ["\']([^"\']+)["\']', version_text)
    if not match:
        raise RuntimeError("Unable to determine package version")
    return match.group(1)


def venv_python(venv_path: Path) -> Path:
    if os.name == "nt":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def run(command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def main() -> None:
    version = get_version()
    wheel = ROOT / "dist" / f"nova_hunting-{version}-py3-none-any.whl"
    if not wheel.is_file():
        raise SystemExit(f"Built wheel not found: {wheel}")

    with tempfile.TemporaryDirectory(prefix="nova-wheel-smoke-") as tmp:
        tmp_path = Path(tmp)
        venv_path = tmp_path / "venv"
        venv.EnvBuilder(with_pip=True).create(venv_path)
        python = venv_python(venv_path)

        run([str(python), "-m", "pip", "install", str(wheel)])

        smoke_code = textwrap.dedent(
            """
            import importlib.metadata as metadata
            import importlib.util as util
            import os
            import sys
            from pathlib import Path

            import nova
            from nova import NovaMatcher, NovaParser

            expected_version = os.environ["NOVA_EXPECTED_VERSION"]
            assert metadata.version("nova-hunting") == expected_version
            assert nova.__version__ == expected_version

            spec = util.find_spec("nova")
            assert spec and spec.origin, "nova package is not importable as an installed artifact"
            package_dir = Path(spec.origin).resolve().parent
            try:
                package_dir.relative_to(Path(sys.prefix).resolve())
            except ValueError as exc:
                raise AssertionError(spec.origin) from exc
            assert (package_dir / "_version.py").is_file()
            assert (package_dir / "utils" / "log_buffer.py").is_file()

            entry_points = metadata.entry_points()
            if hasattr(entry_points, "select"):
                console_scripts = entry_points.select(group="console_scripts")
            else:
                console_scripts = entry_points.get("console_scripts", [])

            assert any(
                entry.name == "novarun" and entry.value == "nova.novarun:main"
                for entry in console_scripts
            ), "novarun console script metadata is missing"

            package_requires = metadata.requires("nova-hunting") or []
            runtime_requires = [
                requirement for requirement in package_requires
                if "extra ==" not in requirement
            ]
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
                "sentence-transformers" in requirement.lower() and 'extra == "semantic"' in requirement
                for requirement in package_requires
            )
            assert any(
                "pip-audit" in requirement.lower() and 'extra == "security"' in requirement
                for requirement in package_requires
            )

            rule = NovaParser().parse('''
            rule WheelKeywordSmoke
            {
                keywords:
                    $inject = "ignore previous instructions"

                condition:
                    keywords.$inject
            }
            ''')
            result = NovaMatcher(rule).check_prompt("please ignore previous instructions")
            assert result["matched"] is True

            print("wheel-smoke-ok")
            """
        )

        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["NOVA_EXPECTED_VERSION"] = version
        run([str(python), "-c", smoke_code], cwd=tmp_path, env=env)

        rule_file = tmp_path / "keyword_rule.nov"
        rule_file.write_text(
            textwrap.dedent(
                """
                rule WheelCliSmoke
                {
                    keywords:
                        $inject = "ignore previous instructions"

                    condition:
                        keywords.$inject
                }
                """
            ),
            encoding="utf-8",
        )

        help_result = run(
            [str(python), "-m", "nova.novarun", "--help"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
        )
        assert "openrouter" in help_result.stdout

        scan_result = run(
            [
                str(python),
                "-m",
                "nova.novarun",
                "--rule",
                str(rule_file),
                "--prompt",
                "please ignore previous instructions",
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
        )
        assert "MATCHED" in scan_result.stdout


if __name__ == "__main__":
    main()
