"""Argument-bound pre-execution checks for Sys1 protection decorators."""

import asyncio
import functools
import inspect

from nova.core.sys1 import NovaEvaluationError
from .exceptions import NovaBlockedError
from .result import ScanResult


def protect_sys1(nova, func, action, severity, param_name, on_block, raise_on_block,
                skip_llm, skip_sys1, state_factory):
    signature = inspect.signature(func)

    def prepare(args, kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        text = bound.arguments.get(param_name)
        if not isinstance(text, str):
            raise NovaEvaluationError(ScanResult("", "", evaluation_complete=False), ["missing_scan_text"])
        try:
            state = state_factory(dict(bound.arguments)) if state_factory else None
        except Exception:
            raise NovaEvaluationError(ScanResult(text, text, evaluation_complete=False), ["invalid_context"]) from None
        return bound, text, state

    def check(result, bound):
        if not result.evaluation_complete:
            raise NovaEvaluationError(result, ["incomplete_evaluation"])
        if nova._should_block(result, action, severity):
            if on_block:
                return False, on_block(result)
            if raise_on_block:
                raise NovaBlockedError(result)
            return False, None
        if result.redacted:
            bound.arguments[param_name] = result.sanitized_text
        return True, None

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        bound, text, state = prepare(args, kwargs)
        result = nova.scan(text, sys1_state=state, skip_sys1=skip_sys1, skip_llm=skip_llm)
        proceed, response = check(result, bound)
        return func(*bound.args, **bound.kwargs) if proceed else response

    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        bound, text, state = prepare(args, kwargs)
        result = await nova.scan_async(text, sys1_state=state, skip_sys1=skip_sys1, skip_llm=skip_llm)
        proceed, response = check(result, bound)
        return await func(*bound.args, **bound.kwargs) if proceed else response

    return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
