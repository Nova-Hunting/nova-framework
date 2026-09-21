import json
import sys
from unittest.mock import Mock

import pytest

from nova import novarun
from nova.evaluators.jev.config import JevConfig
from nova.evaluators.jev.openrouter import OpenRouterJevEvaluator
from nova.utils.config import NovaConfig
from test_jev_parser import source
from test_jev_integration import FixtureEvaluator


def invoke(monkeypatch, tmp_path, args=(), rule_text=None):
    path = tmp_path / "rule.nov"
    path.write_text(rule_text or source("jev.$scope"))
    monkeypatch.setattr(sys, "argv", ["novarun", "--rule", str(path), *args])
    return novarun.main()


def test_cli_disabled_no_network(monkeypatch, tmp_path, capsys):
    request = Mock(side_effect=AssertionError("Network must not run"))
    monkeypatch.setattr(OpenRouterJevEvaluator, "_request", request)
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-key")
    with pytest.raises(SystemExit) as caught:
        invoke(monkeypatch, tmp_path, ["--prompt", "private-action"])
    assert caught.value.code == 1
    output = capsys.readouterr().out
    assert "INCOMPLETE" in output and "Reason: disabled" in output
    assert "private-action" not in output and "synthetic-key" not in output
    request.assert_not_called()


def test_cli_context_batch_model_and_enablement(monkeypatch, tmp_path, capsys):
    contexts = []
    fixture = FixtureEvaluator()

    def evaluate(self, patterns, state):
        assert self.config.enabled
        assert self.config.model == "explicit-model"
        contexts.append(state)
        return fixture.evaluate_many(patterns, state)

    monkeypatch.setattr(OpenRouterJevEvaluator, "evaluate_many", evaluate)
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"approved_task": "test"}))
    prompts = tmp_path / "prompts.txt"
    prompts.write_text("first\nsecond\n")
    invoke(monkeypatch, tmp_path, ["--file", str(prompts), "--jev", "--jev-model", "explicit-model", "--jev-state", str(state)])
    assert contexts == [{"text": text, "context": {"approved_task": "test"}} for text in ("first", "second")]
    assert "Noul $scope: 0.8" in capsys.readouterr().out


def test_cli_invalid_context_or_config_exit_two(monkeypatch, tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"bad": NaN}')
    with pytest.raises(SystemExit) as caught:
        invoke(monkeypatch, tmp_path, ["--prompt", "text", "--jev-state", str(path)])
    assert caught.value.code == 2
    monkeypatch.setenv("NOVA_JEV_TIMEOUT_SECONDS", "0")
    with pytest.raises(SystemExit) as caught:
        invoke(monkeypatch, tmp_path, ["--prompt", "text"])
    assert caught.value.code == 2


def test_config_precedence_and_separation(monkeypatch, tmp_path):
    path = tmp_path / "nova.ini"
    path.write_text('[jev]\nenabled = true\nmodel = file-model\nretries = 1\n[llm]\nmodel = unrelated\n')
    config = NovaConfig(str(path))
    assert JevConfig.resolve(config=config).model == "file-model"
    assert JevConfig.resolve(config=config).enabled
    monkeypatch.setenv("NOVA_JEV_MODEL", "environment-model")
    assert JevConfig.resolve(config=config).model == "environment-model"
    assert JevConfig.resolve({"model": "explicit-model", "enabled": False}, config).model == "explicit-model"
    assert not JevConfig.resolve({"enabled": False}, config).enabled


@pytest.mark.parametrize("options", [{"retries": True}, {"timeout_seconds": 0}, {"provider": "other"}, {"enabled": "yes"}, {"unknown": 1}])
def test_invalid_config(options):
    with pytest.raises(ValueError):
        JevConfig.resolve(options)


@pytest.mark.parametrize("verbose,confidence", [(False, .8), (True, .8), (True, .4)])
def test_verbose_evidence_and_incomplete_diagnostics(monkeypatch, tmp_path, capsys, verbose, confidence):
    fixture = FixtureEvaluator(confidence=confidence)

    def evaluate(self, patterns, state):
        batch = fixture.evaluate_many(patterns, state)
        batch.metadata.update(id="fixture-request", request_count=1, usage={"cost": .001})
        return batch

    monkeypatch.setattr(OpenRouterJevEvaluator, "evaluate_many", evaluate)
    monkeypatch.setenv("OPENROUTER_API_KEY", "private-api-key-marker")
    context = tmp_path / "context.json"
    context.write_text('{"context": "private-context-marker"}')
    args = ["--prompt", "private-prompt-marker", "--jev", "--jev-state", str(context), "--json"]
    if verbose:
        args.append("--verbose")
    if confidence < .6:
        with pytest.raises(SystemExit) as caught:
            invoke(monkeypatch, tmp_path, args, source("jev.$operation"))
        assert caught.value.code == 1
    else:
        invoke(monkeypatch, tmp_path, args, source("jev.$operation"))
    raw = capsys.readouterr().out
    assert all(marker not in raw for marker in ("private-api-key-marker", "private-context-marker", "private-prompt-marker"))
    output = json.loads(raw[raw.index("{"):])
    if not verbose:
        assert "rule_details" not in output and "jev_config" not in output
        return
    rule = output["rule_details"]["Risk"]
    assert output["elapsed_ms"] >= 0
    assert output["jev_config"]["provider"] == "openrouter"
    assert rule["condition"] == "jev.$operation"
    assert rule["jev_batches"][0]["usage"]["cost"] == .001
    assert rule["jev_batches"][0]["id"] == "fixture-request"
    assert rule["condition_result"] == ("unknown" if confidence < .6 else "true")
    if confidence < .6:
        assert not output["evaluation_complete"]
        assert "insufficient_confidence" in rule["evaluation_warnings"][0]


@pytest.mark.parametrize("verbose,confidence", [(False, .8), (True, .8), (False, .4)])
def test_readable_output_shows_all_native_results(monkeypatch, tmp_path, capsys, verbose, confidence):
    fixture = FixtureEvaluator(confidence=confidence, noul=.1)
    monkeypatch.setattr(OpenRouterJevEvaluator, "evaluate_many", lambda self, patterns, state: fixture.evaluate_many(patterns, state))
    rules = "\n".join(source(f"jev.${variable}", name=name) for variable, name in
                       [("scope", "Override"), ("risk", "Impact"), ("operation", "Operation")])
    args = ["--jev", "--prompt", "private-prompt-marker"] + (["--verbose"] if verbose else [])
    if confidence < .6:
        with pytest.raises(SystemExit) as caught:
            invoke(monkeypatch, tmp_path, args, rules)
        assert caught.value.code == 1
    else:
        invoke(monkeypatch, tmp_path, args, rules)
    output = capsys.readouterr().out
    assert "NO MATCH  Override" in output
    assert "Noul $scope: 0.1  |  NO MATCH  |  threshold 0.7" in output
    assert "Score $risk: 2" in output
    assert "Choice $operation: write" in output
    assert "private-prompt-marker" not in output
    assert '"jev_results"' not in output and "null" not in output
    if confidence < .6:
        assert "INCOMPLETE  Impact" in output
        assert "INCOMPLETE  Operation" in output
        assert "Reason: insufficient confidence" in output
    else:
        assert "MATCH  Impact" in output and "MATCH  Operation" in output
    assert ("Condition:" in output) is verbose
    assert ("Probabilities:" in output) is False  # This fixture has no probabilities.


def test_json_batch_is_machine_readable(monkeypatch, tmp_path, capsys):
    fixture = FixtureEvaluator()
    monkeypatch.setattr(OpenRouterJevEvaluator, "evaluate_many", lambda self, patterns, state: fixture.evaluate_many(patterns, state))
    prompts = tmp_path / "prompts.txt"
    prompts.write_text("first\nsecond\n")
    invoke(monkeypatch, tmp_path, ["--jev", "--file", str(prompts), "--json"])
    outputs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [output["prompt_index"] for output in outputs] == [0, 1]
    assert all(output["jev_results"]["Risk"]["$scope"]["answer"]["noul"] == .8 for output in outputs)
