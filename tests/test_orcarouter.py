import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from nova.core.rules import LLMPattern, NovaRule
from nova.core.scanner import NovaScanner
from nova.evaluators.llm import get_validated_evaluator
from nova.novarun import SUPPORTED_LLM_PROVIDERS, apply_config_to_args
from nova.sdk import Nova
from nova.utils.config import NovaConfig


def test_orcarouter_requires_its_own_key(monkeypatch):
    monkeypatch.delenv("ORCAROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    with pytest.raises(ValueError, match="ORCAROUTER_API_KEY"):
        get_validated_evaluator("orcarouter")


def test_orcarouter_model_precedence(monkeypatch):
    monkeypatch.setenv("ORCAROUTER_API_KEY", "test-orcarouter-key")
    for name in ("ORCAROUTER_LLM_MODEL", "ORCAROUTER_MODEL", "NOVA_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert get_validated_evaluator("orcarouter").model == "orcarouter/auto"
    for name, model in (
        ("NOVA_LLM_MODEL", "openai/gpt-4o-mini"),
        ("ORCAROUTER_MODEL", "google/gemini-2.5-flash"),
        ("ORCAROUTER_LLM_MODEL", "anthropic/claude-sonnet-4"),
    ):
        monkeypatch.setenv(name, model)
        assert get_validated_evaluator("orcarouter").model == model
    assert get_validated_evaluator("orcarouter", model="explicit/model").model == "explicit/model"
    assert NovaConfig().get("api_keys", "orcarouter") == "test-orcarouter-key"


@pytest.mark.parametrize("model", ["orcarouter/auto", "openai/gpt-4o-mini"])
def test_orcarouter_request_and_cache(monkeypatch, model):
    monkeypatch.setenv("ORCAROUTER_API_KEY", "test-orcarouter-key")
    response = Mock(status_code=200)
    response.json.return_value = {
        "choices": [{"message": {"content": json.dumps({"matched": True, "confidence": 0.9})}}]
    }
    session = Mock()
    session.post.return_value = response
    evaluator = get_validated_evaluator("orcarouter", model=model)
    evaluator.session = session
    prompt, text = "Detect unsafe content", f"orcarouter test {model}"
    matched, confidence, details = evaluator.evaluate_prompt(prompt, text)
    assert (matched, confidence) == (True, 0.9)
    assert details["evaluator_type"] == "orcarouter"
    args, kwargs = session.post.call_args
    assert args == ("https://api.orcarouter.ai/v1/chat/completions",)
    assert kwargs["headers"]["Authorization"] == "Bearer test-orcarouter-key"
    assert kwargs["json"]["model"] == model
    assert kwargs["json"]["response_format"] == {"type": "json_object"}
    if model.startswith("orcarouter/"):
        assert "temperature" not in kwargs["json"]
    else:
        assert kwargs["json"]["temperature"] == 0.1
    assert evaluator.evaluate_prompt(prompt, text)[2]["cache_hit"]
    assert session.post.call_count == 1
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "test-gateway-key")
    other = get_validated_evaluator("vercel", model=model)
    other.session = session
    assert "cache_hit" not in other.evaluate_prompt(prompt, text)[2]
    assert session.post.call_count == 2


def test_orcarouter_cli_config_scanner_and_sdk(tmp_path, monkeypatch):
    for name in ("ORCAROUTER_API_KEY", "ORCAROUTER_LLM_MODEL", "ORCAROUTER_MODEL", "NOVA_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    config = tmp_path / "nova.ini"
    config.write_text("[llm]\nprovider = orcarouter\nmodel = orcarouter/auto\n"
                      "[api_keys]\norcarouter = test-config-key\n")
    args = SimpleNamespace(config=str(config), llm=None, model=None)
    apply_config_to_args(args)
    assert args.llm == "orcarouter"
    assert "orcarouter" in SUPPORTED_LLM_PROVIDERS
    evaluator = get_validated_evaluator(args.llm, args.model)
    assert evaluator.api_key == "test-config-key"
    assert evaluator.model == "orcarouter/auto"
    rule = NovaRule(name="OrcaRouterRule", llms={"$judge": LLMPattern("Detect unsafe content")},
                    condition="llm.$judge")
    scanner = NovaScanner([rule], llm_type="orcarouter")
    nova = Nova(llm_provider="orcarouter")
    nova.add_rule(rule)
    assert scanner._llm_evaluator.evaluator_type == "orcarouter"
    assert nova._matchers[rule.name].llm_evaluator.evaluator_type == "orcarouter"
