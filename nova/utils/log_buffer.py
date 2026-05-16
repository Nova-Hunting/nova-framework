"""
In-memory log buffering for Nova.

This module preserves the logger extension points used by applications that
stream Nova logs in real time.
"""

import logging
import os
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Union


DEFAULT_BUFFER_SIZE = 1000
_GLOBAL_BUFFER = None
_GLOBAL_BUFFER_LOCK = threading.Lock()


def _coerce_level(level: Optional[Union[int, str]]) -> int:
    if level is None:
        return logging.NOTSET
    if isinstance(level, int):
        return level
    return getattr(logging, level.upper(), logging.NOTSET)


class LogRingBuffer(logging.Handler):
    """A bounded logging handler that stores recent records in memory."""

    def __init__(self, capacity: Optional[int] = None, level: Optional[Union[int, str]] = None):
        size = capacity or int(os.environ.get("NOVA_LOG_BUFFER_SIZE", DEFAULT_BUFFER_SIZE))
        super().__init__(_coerce_level(level))
        self.capacity = max(1, size)
        self._records: Deque[Dict[str, Any]] = deque(maxlen=self.capacity)
        self._lock = threading.RLock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "module": record.module,
                "function": record.funcName,
                "line": record.lineno,
            }
            if record.exc_info:
                entry["exception"] = logging.Formatter().formatException(record.exc_info)
            with self._lock:
                self._records.append(entry)
        except Exception:
            self.handleError(record)

    def get_logs(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._lock:
            records = list(self._records)
        if limit is not None:
            return records[-limit:]
        return records

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    @property
    def records(self) -> List[Dict[str, Any]]:
        return self.get_logs()


def get_log_buffer(capacity: Optional[int] = None) -> LogRingBuffer:
    """Return the process-wide Nova log ring buffer."""
    global _GLOBAL_BUFFER
    if _GLOBAL_BUFFER is None:
        with _GLOBAL_BUFFER_LOCK:
            if _GLOBAL_BUFFER is None:
                _GLOBAL_BUFFER = LogRingBuffer(capacity=capacity)
    return _GLOBAL_BUFFER


def install_buffer_handler(
    logger: Optional[logging.Logger] = None,
    logger_name: str = "nova",
    capacity: Optional[int] = None,
    level: Optional[Union[int, str]] = None,
) -> LogRingBuffer:
    """
    Attach the global buffer handler to a logger if it is not already attached.
    """
    target_logger = logger or logging.getLogger(logger_name)
    buffer_handler = get_log_buffer(capacity=capacity)
    if level is not None:
        buffer_handler.setLevel(_coerce_level(level))

    for handler in target_logger.handlers:
        if handler is buffer_handler:
            return buffer_handler

    target_logger.addHandler(buffer_handler)
    return buffer_handler


def uninstall_buffer_handler(logger: Optional[logging.Logger] = None, logger_name: str = "nova") -> None:
    """Detach the global buffer handler from a logger."""
    target_logger = logger or logging.getLogger(logger_name)
    buffer_handler = get_log_buffer()
    if buffer_handler in target_logger.handlers:
        target_logger.removeHandler(buffer_handler)


def clear_log_buffer() -> None:
    """Clear the process-wide Nova log buffer."""
    get_log_buffer().clear()
