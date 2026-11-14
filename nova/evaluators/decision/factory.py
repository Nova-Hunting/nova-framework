"""Create HTTP adapters for the configured decision provider."""

from .config import DecisionConfig


def create_decision_evaluator(config=None):
    config = DecisionConfig.resolve(config)
    if config.provider == "ollama":
        from .ollama import OllamaDecisionEvaluator
        return OllamaDecisionEvaluator(config)
    from .openrouter import OpenRouterDecisionEvaluator
    return OpenRouterDecisionEvaluator(config)
