"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia 
twitter: @fr0gger_
License: MIT License
Version: see nova._version
Description: Main Nova framework package initialization
"""

from nova._version import __version__

# NOTE: Transformers configuration for clean_up_tokenization_spaces is done lazily
# in nova/evaluators/semantics.py when the semantic model is first loaded.
# This avoids loading torch/transformers (~1 second) for keyword-only matching.

from nova.core.rules import (
    KeywordPattern,
    SemanticPattern,
    LLMPattern,
    NovaRule
)
from nova.core.matcher import NovaMatcher
from nova.core.parser import NovaParser
from nova.core.scanner import NovaScanner
from nova.utils.config import NovaConfig
from nova.utils.logger import LOG_FORMATS, get_logger, set_log_format, set_log_level
from nova.utils.log_buffer import get_log_buffer, install_buffer_handler

# SDK imports
from nova.sdk import (
    Nova,
    ScanResult,
    RuleMatch,
    NovaPolicy,
    PolicyRule,
    Action,
    Redactor,
    NovaBlockedError,
    protect,
    scan,
)

__all__ = [
    '__version__',

    # Core classes
    'KeywordPattern',
    'SemanticPattern',
    'LLMPattern',
    'NovaRule',
    'NovaMatcher',
    'NovaParser',
    'NovaScanner',
    'NovaConfig',
    'LOG_FORMATS',
    'get_logger',
    'set_log_format',
    'set_log_level',
    'get_log_buffer',
    'install_buffer_handler',

    # SDK classes
    'Nova',
    'ScanResult',
    'RuleMatch',
    'NovaPolicy',
    'PolicyRule',
    'Action',
    'Redactor',
    'NovaBlockedError',
    'protect',
    'scan',
]
