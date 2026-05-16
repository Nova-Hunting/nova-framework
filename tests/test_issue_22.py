import logging

from nova.evaluators.condition import (
    can_llm_change_outcome,
    can_semantics_change_outcome,
    evaluate_condition,
)
from nova.evaluators.llm import get_validated_evaluator
from nova.utils import LOG_FORMATS, get_log_buffer, install_buffer_handler, set_log_format


def test_n_of_section_wildcard_evaluates_before_section_wildcard_replacement():
    assert evaluate_condition(
        "2 of keywords.*",
        {"$one": True, "$two": True, "$three": False},
        {},
        {},
    ) is True
    assert evaluate_condition(
        "2 of keywords.*",
        {"$one": True, "$two": False},
        {},
        {},
    ) is False


def test_condition_evaluator_rejects_python_expressions():
    assert evaluate_condition(
        "keywords.$hit or ().__class__.__mro__",
        {"$hit": True},
        {},
        {},
    ) is False

    assert evaluate_condition(
        "keywords.$hit and __import__('os')",
        {"$hit": True},
        {},
        {},
    ) is False


def test_condition_change_helpers_are_not_placeholder_stubs():
    assert can_semantics_change_outcome("semantics.$similar", {}) is True
    assert can_semantics_change_outcome("keywords.$hit and semantics.$similar", {"$hit": False}) is False

    assert can_llm_change_outcome("llm.$judge", {}, {}) is True
    assert can_llm_change_outcome("keywords.$hit and llm.$judge", {"$hit": False}, {}) is False


def test_condition_change_helpers_handle_negated_later_stage_patterns():
    assert can_semantics_change_outcome("not semantics.$safe", {}) is True
    assert can_llm_change_outcome("not llm.$safe", {}, {}) is True


def test_log_format_and_buffer_compatibility_exports():
    logger = logging.getLogger("nova.issue22")
    logger.handlers.clear()
    stream_handler = logging.StreamHandler()
    logger.addHandler(stream_handler)

    assert "simple" in LOG_FORMATS
    assert "detailed" in LOG_FORMATS
    assert "json" in LOG_FORMATS

    set_log_format("json")
    assert stream_handler.formatter is not None

    buffer_handler = install_buffer_handler(logger=logger, capacity=10)
    buffer_handler.clear()
    logger.warning("buffered warning")

    logs = get_log_buffer().get_logs()
    assert logs[-1]["message"] == "buffered warning"
    assert logs[-1]["logger"] == "nova.issue22"


def test_provider_specific_env_model_override(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_LLM_MODEL", "gpt-test-env")

    evaluator = get_validated_evaluator("openai")
    assert evaluator.model == "gpt-test-env"

    explicit = get_validated_evaluator("openai", model="gpt-explicit")
    assert explicit.model == "gpt-explicit"
