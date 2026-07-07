"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia
twitter: @fr0gger_
License: MIT License
Version: see nova._version
Description: Utility functions for Nova framework
"""

from nova.utils.config import NovaConfig, get_config
from nova.utils.logger import LOG_FORMATS, get_logger, set_log_format, set_log_level
from nova.utils.helpers import normalize_unicode, remove_zero_width_chars
from nova.utils.log_buffer import (
    LogRingBuffer,
    clear_log_buffer,
    get_log_buffer,
    install_buffer_handler,
    uninstall_buffer_handler,
)

__all__ = [
    'NovaConfig',
    'get_config',
    'LOG_FORMATS',
    'get_logger',
    'set_log_format',
    'set_log_level',
    'normalize_unicode',
    'remove_zero_width_chars',
    'LogRingBuffer',
    'clear_log_buffer',
    'get_log_buffer',
    'install_buffer_handler',
    'uninstall_buffer_handler',
]
