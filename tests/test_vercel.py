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


def test_vercel_requires_gateway_key(monkeypatch):
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    with pytest.raises(ValueError, match="AI_GATEWAY_API_KEY"):
        get_validated_evaluator("vercel")


def test_vercel_model_precedence(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "test-gateway-key")
    for name in ("AI_GATEWAY_LLM_MODEL", "AI_GATEWAY_MODEL", "NOVA_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert get_validated_evaluator("vercel").model == "openai/gpt-4o-mini"
    for name, model in (
        ("NOVA_LLM_MODEL", "openai/gpt-4o"),
        ("AI_GATEWAY_MODEL", "google/gemini-2.5-flash"),
        ("AI_GATEWAY_LLM_MODEL", "anthropic/claude-sonnet-4"),
    ):
        monkeypatch.setenv(name, model)
        assert get_validated_evaluator("vercel").model == model
    assert get_validated_evaluator("vercel", model="explicit/model").model == "explicit/model"
    assert NovaConfig().get("api_keys", "vercel") == "test-gateway-key"


def test_vercel_request_and_cache_are_scoped_to_provider(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "test-gateway-key")
    response = Mock(status_code=200)
    response.json.return_value = {
        "choices": [{"message": {"content": json.dumps({"matched": True, "confidence": 0.9})}}]
    }
    session = Mock()
    session.post.return_value = response
    gateway = get_validated_evaluator("vercel", model="openai/gpt-4o-mini")
    gateway.session = session
    matched, confidence, details = gateway.evaluate_prompt("Detect unsafe content", "vercel test prompt")
    assert (matched, confidence) == (True, 0.9)
    assert details["evaluator_type"] == "vercel"
    assert details["model"] == "openai/gpt-4o-mini"
    args, kwargs = session.post.call_args
    assert args == ("https://ai-gateway.vercel.sh/v1/chat/completions",)
    assert kwargs["headers"]["Authorization"] == "Bearer test-gateway-key"
    assert kwargs["json"]["model"] == "openai/gpt-4o-mini"
    assert kwargs["json"]["response_format"] == {"type": "json_object"}
    assert gateway.evaluate_prompt("Detect unsafe content", "vercel test prompt")[2]["cache_hit"]
    assert session.post.call_count == 1
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    other = get_validated_evaluator("openrouter", model="openai/gpt-4o-mini")
    other.session = session
    assert "cache_hit" not in other.evaluate_prompt("Detect unsafe content", "vercel test prompt")[2]
    assert session.post.call_count == 2


def test_vercel_cli_config_scanner_and_sdk(tmp_path, monkeypatch):
    for name in ("AI_GATEWAY_API_KEY", "AI_GATEWAY_LLM_MODEL", "AI_GATEWAY_MODEL", "NOVA_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    config = tmp_path / "nova.ini"
    config.write_text("[llm]\nprovider = vercel\nmodel = openai/gpt-4o-mini\n"
                      "[api_keys]\nvercel = test-config-key\n")
    args = SimpleNamespace(config=str(config), llm=None, model=None)
    apply_config_to_args(args)
    assert args.llm == "vercel"
    assert "vercel" in SUPPORTED_LLM_PROVIDERS
    evaluator = get_validated_evaluator(args.llm, args.model)
    assert evaluator.api_key == "test-config-key"
    assert evaluator.model == "openai/gpt-4o-mini"
    rule = NovaRule(name="VercelRule", llms={"$judge": LLMPattern("Detect unsafe content")},
                    condition="llm.$judge")
    scanner = NovaScanner([rule], llm_type="vercel")
    nova = Nova(llm_provider="vercel")
    nova.add_rule(rule)
    assert scanner._llm_evaluator.evaluator_type == "vercel"
    assert nova._matchers[rule.name].llm_evaluator.evaluator_type == "vercel"
