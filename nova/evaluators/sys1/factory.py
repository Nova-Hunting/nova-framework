"""Create lightweight adapters without importing a local inference runtime."""

from .config import Sys1Config


def create_sys1_evaluator(config=None):
    config = Sys1Config.resolve(config)
    if config.provider == "laya":
        from .laya import LayaSys1Evaluator
        return LayaSys1Evaluator(config)
    from .openrouter import OpenRouterSys1Evaluator
    return OpenRouterSys1Evaluator(config)
