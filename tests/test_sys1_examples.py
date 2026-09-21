import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("mode", ["prompt", "typed", "agent"])
def test_fixture_demos_are_executable(mode):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run([sys.executable, str(ROOT / "examples/sys1/demo.py"), mode],
                            capture_output=True, text=True, env=env, check=True)
    assert "FIXTURE OUTPUT" in result.stdout
    if mode == "typed":
        assert '"score": 2.2' in result.stdout and '"confidence": 0.8' in result.stdout
    if mode == "agent":
        assert "STUB BLOCKED before execution" in result.stdout
        assert "STUB EXECUTED" not in result.stdout


def test_fixture_quality_harness_marks_its_limits():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run([sys.executable, str(ROOT / "examples/sys1/evaluate_quality.py"), "--limit", "9"],
                            capture_output=True, text=True, env=env, check=True)
    assert '"http_requests": 0' in result.stdout
    assert '"indeterminate": 1' in result.stdout
    assert "not detection-quality measurements" in result.stdout
