import json

import pytest

from nova.evaluators.llm import (
    OpenRouterEvaluator,
    _LLM_CACHE_LOCK,
    _LLM_RESPONSE_CACHE,
    get_validated_evaluator,
)
from nova.utils.config import NovaConfig


def clear_llm_cache():
    with _LLM_CACHE_LOCK:
        _LLM_RESPONSE_CACHE.clear()


def test_openrouter_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        get_validated_evaluator("openrouter")


def test_openrouter_default_and_env_model_selection(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.delenv("OPENROUTER_LLM_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.delenv("NOVA_LLM_MODEL", raising=False)

    default = get_validated_evaluator("openrouter")
    assert isinstance(default, OpenRouterEvaluator)
    assert default.model == "openai/gpt-5.2"

    monkeypatch.setenv("OPENROUTER_LLM_MODEL", "anthropic/claude-sonnet-4")
    env_model = get_validated_evaluator("openrouter")
    assert env_model.model == "anthropic/claude-sonnet-4"

    explicit = get_validated_evaluator("openrouter", model="google/gemini-2.5-pro")
    assert explicit.model == "google/gemini-2.5-pro"


def test_openrouter_model_alias_selection(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.delenv("OPENROUTER_LLM_MODEL", raising=False)
    monkeypatch.setenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct")

    evaluator = get_validated_evaluator("openrouter")
    assert evaluator.model == "meta-llama/llama-3.1-8b-instruct"


def test_openrouter_evaluate_prompt_uses_openrouter_endpoint_without_attribution_headers():
    clear_llm_cache()
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({
                                "matched": True,
                                "confidence": 0.84,
                                "reason": "matched test condition",
                            })
                        }
                    }
                ]
            }

    class FakeSession:
        def post(self, *args, **kwargs):
            calls.append((args, kwargs))
            return FakeResponse()

    evaluator = OpenRouterEvaluator(api_key="test-openrouter-key", model="openai/gpt-5.2")
    evaluator.session = FakeSession()

    matched, confidence, details = evaluator.evaluate_prompt("Detect policy violations", "unique openrouter text")

    assert matched is True
    assert confidence == 0.84
    assert details["evaluator_type"] == "openrouter"
    assert details["model"] == "openai/gpt-5.2"

    args, kwargs = calls[0]
    assert args[0] == "https://openrouter.ai/api/v1/chat/completions"
    assert kwargs["headers"]["Authorization"] == "Bearer test-openrouter-key"
    assert "HTTP-Referer" not in kwargs["headers"]
    assert "X-OpenRouter-Title" not in kwargs["headers"]
    assert kwargs["json"]["model"] == "openai/gpt-5.2"


def test_openrouter_cache_is_scoped_by_temperature():
    clear_llm_cache()
    calls = []

    class FakeResponse:
        status_code = 200

        def __init__(self, confidence):
            self.confidence = confidence

        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({
                                "matched": True,
                                "confidence": self.confidence,
                                "reason": "matched test condition",
                            })
                        }
                    }
                ]
            }

    class FakeSession:
        def post(self, *args, **kwargs):
            calls.append((args, kwargs))
            return FakeResponse(0.5 + (len(calls) / 10))

    evaluator = OpenRouterEvaluator(api_key="test-openrouter-key", model="openai/gpt-5.2")
    evaluator.session = FakeSession()

    first = evaluator.evaluate_prompt("Detect policy violations", "cache temperature text", temperature=0.1)
    second = evaluator.evaluate_prompt("Detect policy violations", "cache temperature text", temperature=0.1)
    third = evaluator.evaluate_prompt("Detect policy violations", "cache temperature text", temperature=0.9)

    assert len(calls) == 2
    assert first[1] == second[1] == 0.6
    assert second[2]["cache_hit"] is True
    assert third[1] == 0.7
    assert third[2]["temperature"] == 0.9


def test_openrouter_api_key_is_loaded_by_config(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")

    config = NovaConfig()
    assert config.get("api_keys", "openrouter") == "test-openrouter-key"


def test_supported_provider_api_keys_are_loaded_by_config(monkeypatch):
    provider_env = {
        "OPENAI_API_KEY": ("openai", "test-openai-key"),
        "ANTHROPIC_API_KEY": ("anthropic", "test-anthropic-key"),
        "AZURE_OPENAI_API_KEY": ("azure_openai", "test-azure-key"),
        "GROQ_API_KEY": ("groq", "test-groq-key"),
        "OPENROUTER_API_KEY": ("openrouter", "test-openrouter-key"),
    }

    for env_name, (_, value) in provider_env.items():
        monkeypatch.setenv(env_name, value)

    config = NovaConfig()

    for _, (config_key, value) in provider_env.items():
        assert config.get("api_keys", config_key) == value


def test_provider_runtime_endpoints_are_loaded_by_config(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://nova-test.openai.azure.com")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")

    config = NovaConfig()

    assert config.get("llm", "endpoint") == "https://nova-test.openai.azure.com"
    assert config.get("llm", "host") == "http://127.0.0.1:11434"


def test_explicit_config_path_must_exist(tmp_path):
    missing_config = tmp_path / "missing.ini"

    with pytest.raises(ValueError, match="Config file not found"):
        NovaConfig(str(missing_config))


def test_explicit_json_config_must_be_valid_object(tmp_path):
    config_file = tmp_path / "nova.json"
    config_file.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="JSON config root must be an object"):
        NovaConfig(str(config_file))


def test_config_save_accepts_basename_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    config = NovaConfig()
    config.set("llm", "provider", "openrouter")
    config.save("nova.ini")

    saved_config = tmp_path / "nova.ini"
    assert saved_config.exists()

    reloaded = NovaConfig(str(saved_config))
    assert reloaded.get("llm", "provider") == "openrouter"


def test_config_save_failure_raises(tmp_path):
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("occupied", encoding="utf-8")

    config = NovaConfig()

    with pytest.raises(ValueError, match="Failed to save config"):
        config.save(str(blocking_file / "nova.ini"))
