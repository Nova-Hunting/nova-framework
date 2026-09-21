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
    assert "Incomplete evaluation: disabled" in output
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
    assert '"noul": 0.8' in capsys.readouterr().out


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
