"""Explicit Jev configuration, independent from NOVA's LLM settings."""

from dataclasses import dataclass, fields
import math
import os


@dataclass(frozen=True)
class JevConfig:
    enabled: bool = False
    provider: str = "openrouter"
    model: str = "typesafe/jev-1.13"
    connect_timeout_seconds: float = 3
    timeout_seconds: float = 15
    retries: int = 1
    max_concurrency: int = 4
    max_request_bytes: int = 131072
    max_response_bytes: int = 1048576

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError("Jev enabled must be boolean")
        if self.provider != "openrouter":
            raise ValueError("Jev provider must be openrouter")
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("Jev model must be nonempty")
        for name in ("connect_timeout_seconds", "timeout_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 < value <= 120:
                raise ValueError(f"Jev {name} must be within (0, 120]")
        for name, low, high in (("retries", 0, 2), ("max_concurrency", 1, 32),
                                ("max_request_bytes", 1, 10485760), ("max_response_bytes", 1, 10485760)):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"Jev {name} must be an integer within [{low}, {high}]")

    @classmethod
    def resolve(cls, options=None, config=None):
        if isinstance(options, cls):
            return options
        if config is None:
            from nova.utils.config import get_config
            config = get_config()
        values = dict(config.config.get("jev", {}))
        for field in fields(cls):
            value = os.environ.get("NOVA_JEV_" + field.name.upper())
            if value is not None:
                if field.name == "enabled":
                    if value.lower() not in ("true", "false", "1", "0", "yes", "no"):
                        raise ValueError("NOVA_JEV_ENABLED must be boolean")
                    value = value.lower() in ("true", "1", "yes")
                elif field.type in (int, float):
                    value = field.type(value)
                values[field.name] = value
        # NovaConfig historically reads INI 0/1 as booleans, including numeric fields.
        for field in fields(cls):
            if field.type in (int, float) and isinstance(values.get(field.name), bool):
                values[field.name] = field.type(values[field.name])
        values.update(options or {})
        unknown = set(values) - {field.name for field in fields(cls)}
        if unknown:
            raise ValueError("Unknown Jev settings: " + ", ".join(sorted(unknown)))
        return cls(**values)
