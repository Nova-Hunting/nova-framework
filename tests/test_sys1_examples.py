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


def test_provider_comparison_retains_negative_and_incomplete_results(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "examples/sys1"))
    from compare_providers import assess
    from test_sys1_integration import FixtureEvaluator, rule
    from nova.sdk import Nova
    for confidence, noul, condition, indeterminate in [(.8, .1, "sys1.$scope", 1), (.1, .8, "sys1.$operation", 2)]:
        nova = Nova(rules=[rule(condition)], sys1_config={"enabled": True},
                    sys1_evaluator=FixtureEvaluator(confidence=confidence, noul=noul))
        report = assess(nova, [("sample", "Read", "Read", False), ("missing", "", "Read", None)])
        assert report["cases"][0]["results"]["Risk"]
        assert report["metrics"]["indeterminate"] == indeterminate
        assert report["metrics"]["reported_api_cost"] is None
