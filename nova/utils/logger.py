"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia
twitter: @fr0gger_
License: MIT License
Version: see nova._version
Description: Centralized logging configuration for Nova framework
"""

import logging
import os
import json
from datetime import datetime, timezone
from typing import Iterable, Optional

# Default log level from environment or INFO
DEFAULT_LOG_LEVEL = os.environ.get("NOVA_LOG_LEVEL", "INFO").upper()

# Valid log levels
VALID_LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

LOG_FORMATS = {
    "simple": "[%(levelname)s] %(message)s",
    "detailed": "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s",
    "json": "json",
}

_MANAGED_LOGGER_PREFIXES = (
    "nova",
    "openai",
    "anthropic",
    "groq",
    "httpx",
    "urllib3",
    "requests",
    "sentence_transformers",
    "transformers",
)


def _env_flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


class _JsonFormatter(logging.Formatter):
    """Format log records as compact JSON for structured log consumers."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _build_formatter(format_name: Optional[str] = None) -> logging.Formatter:
    requested_format = format_name or os.environ.get("NOVA_LOG_FORMAT", "simple")
    normalized = requested_format.lower()

    if normalized == "json":
        return _JsonFormatter()

    format_string = LOG_FORMATS.get(normalized, requested_format)
    return logging.Formatter(format_string)


def _iter_managed_loggers() -> Iterable[logging.Logger]:
    seen = set()
    for logger_name in ("nova", *logging.Logger.manager.loggerDict.keys()):
        if logger_name in seen:
            continue
        seen.add(logger_name)
        if logger_name == "nova" or logger_name.startswith(_MANAGED_LOGGER_PREFIXES):
            yield logging.getLogger(logger_name)


def _install_buffer_handler_if_enabled(logger: logging.Logger) -> None:
    if not _env_flag("NOVA_LOG_BUFFER_ENABLED"):
        return

    try:
        from nova.utils.log_buffer import install_buffer_handler
        install_buffer_handler(logger=logger)
    except Exception:
        logger.debug("Failed to install Nova log buffer handler", exc_info=True)


def get_logger(name: str = "nova") -> logging.Logger:
    """
    Get a configured logger instance for Nova framework.

    Args:
        name: Logger name (defaults to 'nova')

    Returns:
        Configured logger instance

    Environment Variables:
        NOVA_LOG_LEVEL: Set log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        NOVA_LOG_FORMAT: Custom log format string
    """
    logger = logging.getLogger(name)

    # Only configure if no handlers exist (avoid duplicate handlers)
    if not logger.handlers:
        # Get log level from environment or use default
        log_level_str = os.environ.get("NOVA_LOG_LEVEL", DEFAULT_LOG_LEVEL)
        log_level = VALID_LOG_LEVELS.get(log_level_str, logging.INFO)
        logger.setLevel(log_level)

        # Create console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)

        formatter = _build_formatter()
        console_handler.setFormatter(formatter)

        # Add handler to logger
        logger.addHandler(console_handler)

        # Prevent propagation to root logger
        logger.propagate = False

    _install_buffer_handler_if_enabled(logger)
    return logger


def set_log_level(level: str) -> None:
    """
    Set the log level for all Nova loggers.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Raises:
        ValueError: If level is not a valid log level
    """
    level_upper = level.upper()
    if level_upper not in VALID_LOG_LEVELS:
        raise ValueError(
            f"Invalid log level: {level}. "
            f"Valid levels: {', '.join(VALID_LOG_LEVELS.keys())}"
        )

    log_level = VALID_LOG_LEVELS[level_upper]

    for logger in _iter_managed_loggers():
        logger.setLevel(log_level)
        for handler in logger.handlers:
            handler.setLevel(log_level)


def set_log_format(format_name: str) -> None:
    """
    Set the output format for all managed Nova-related loggers.

    Args:
        format_name: One of "simple", "detailed", "json", or a logging format string
    """
    formatter = _build_formatter(format_name)
    for logger in _iter_managed_loggers():
        for handler in logger.handlers:
            handler.setFormatter(formatter)


# Create default logger instance
logger = get_logger("nova")
