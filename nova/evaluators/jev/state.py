"""Snapshot caller-owned JSON state without coercion or truncation."""

import json
import math


def snapshot_state(text, context=None, max_bytes=131072):
    if not isinstance(text, str):
        raise ValueError("Scan text must be a string")
    seen = set()

    def copy(value, depth=0):
        if depth > 64:
            raise ValueError("Jev state exceeds maximum nesting depth")
        if value is None or type(value) in (str, bool, int):
            return value
        if type(value) is float:
            if not math.isfinite(value):
                raise ValueError("Jev state contains a nonfinite number")
            return value
        if type(value) not in (dict, list):
            raise ValueError("Jev state must contain only JSON values")
        if id(value) in seen:
            raise ValueError("Jev state contains a cycle")
        seen.add(id(value))
        if isinstance(value, dict):
            if any(type(key) is not str for key in value):
                raise ValueError("Jev state object keys must be strings")
            result = {key: copy(item, depth + 1) for key, item in value.items()}
        else:
            result = [copy(item, depth + 1) for item in value]
        seen.remove(id(value))
        return result

    if context is not None and type(context) not in (str, dict, list):
        raise ValueError("Jev context must be a string, object or array")
    state = text if context is None else {"text": text, "context": copy(context)}
    if len(json.dumps(state, ensure_ascii=False, allow_nan=False).encode("utf-8")) > max_bytes:
        raise ValueError("Jev state exceeds request size limit")
    return state
