"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia
twitter: @fr0gger_
License: MIT License
Version: see nova._version
Description: Semantic pattern evaluator implementations
"""

from typing import Tuple
from collections import OrderedDict
import threading
from nova.core.rules import SemanticPattern
from nova.evaluators.base import SemanticEvaluator
from nova.utils.logger import get_logger

# Get logger for this module
logger = get_logger("nova.evaluators.semantics")


class LRUCache(OrderedDict):
    """LRU cache with max size to prevent unbounded memory growth."""

    def __init__(self, maxsize: int = 10000):
        super().__init__()
        self.maxsize = maxsize

    def __getitem__(self, key):
        value = super().__getitem__(key)
        self.move_to_end(key)  # Move to end (most recently used)
        return value

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        # Evict oldest entry if over capacity
        if len(self) > self.maxsize:
            oldest = next(iter(self))
            del self[oldest]

    def __contains__(self, key):
        return OrderedDict.__contains__(self, key)


# Global model cache to prevent reloading models
_MODEL_CACHE = {}
_EMBEDDING_CACHE = {}  # Cache for pattern embeddings (bounded by number of patterns)
_TEXT_EMBEDDING_CACHE = LRUCache(maxsize=10000)  # LRU cache for text embeddings

# Threading locks for thread-safe cache access
_MODEL_CACHE_LOCK = threading.Lock()
_EMBEDDING_CACHE_LOCK = threading.Lock()
_TEXT_EMBEDDING_LOCK = threading.Lock()

class DefaultSemanticEvaluator(SemanticEvaluator):
    """
    Default semantic evaluator using sentence transformers.
    Performs semantic similarity matching between patterns and text.
    """
    
    def __init__(self, model_name: str = 'all-MiniLM-L6-v2'):  
        """
        Initialize the semantic evaluator with a sentence transformer model.
        
        Args:
            model_name: Name of the sentence transformer model to use
        """
        self.model_name = model_name
        self.model = None
        self.last_error = None
        # Use the global embedding cache instead of instance-specific cache
        # Model is loaded lazily on first evaluate() call
    
    def _load_model(self) -> bool:
        """
        Load the sentence transformer model from global cache if available (thread-safe).

        Returns:
            Boolean indicating whether the model was successfully loaded
        """
        global _MODEL_CACHE

        # If model already loaded on this instance, return it
        if self.model is not None:
            self.last_error = None
            return True

        # Check if model exists in global cache (with lock)
        with _MODEL_CACHE_LOCK:
            if self.model_name in _MODEL_CACHE:
                self.model = _MODEL_CACHE[self.model_name]
                self.last_error = None
                return True

            try:
                # Import here to avoid dependency issues if not needed
                from sentence_transformers import SentenceTransformer

                # Configure transformers to avoid FutureWarning (moved here from nova/__init__.py
                # to avoid loading torch/transformers at import time for keyword-only matching)
                try:
                    import transformers
                    if hasattr(transformers, 'tokenization_utils_base'):
                        transformers.tokenization_utils_base.CLEAN_UP_TOKENIZATION_SPACES = True
                    if hasattr(transformers, 'PreTrainedTokenizerBase'):
                        transformers.PreTrainedTokenizerBase.clean_up_tokenization_spaces = True
                except ImportError:
                    pass

                self.model = SentenceTransformer(self.model_name)

                # Explicitly set clean_up_tokenization_spaces to True to avoid the FutureWarning
                if hasattr(self.model, 'tokenizer'):
                    self.model.tokenizer.clean_up_tokenization_spaces = True

                _MODEL_CACHE[self.model_name] = self.model
                self.last_error = None
                return True
            except Exception as e:
                self.last_error = str(e)
                logger.warning(f"Could not load semantic model ({self.model_name}): {e}")
                logger.warning("Semantic matching will not be available.")
                return False

    def encode_text(self, text: str):
        """
        Encode text once and return the embedding for reuse across multiple pattern comparisons (thread-safe).

        Args:
            text: The text to encode

        Returns:
            The text embedding tensor, or None if model not available or text is invalid
        """
        # Input validation - handle None/empty text gracefully
        if text is None or not isinstance(text, str) or not text.strip():
            return None

        if not self._load_model():
            return None

        text_key = f"{self.model_name}:{text}"
        with _TEXT_EMBEDDING_LOCK:
            if text_key not in _TEXT_EMBEDDING_CACHE:
                _TEXT_EMBEDDING_CACHE[text_key] = self.model.encode([text], convert_to_tensor=True)
            return _TEXT_EMBEDDING_CACHE[text_key]

    def evaluate_with_embedding(self, pattern: SemanticPattern, text_embedding) -> Tuple[bool, float]:
        """
        Evaluate a pattern against a pre-computed text embedding (thread-safe).
        This is more efficient when comparing multiple patterns against the same text.

        Args:
            pattern: The SemanticPattern to match
            text_embedding: Pre-computed text embedding from encode_text()

        Returns:
            Tuple of (match_success, similarity_score)
        """
        if text_embedding is None:
            return False, 0.0

        try:
            from sentence_transformers import util

            # Get pattern embedding (should already be cached from initialization)
            pattern_key = f"{self.model_name}:{pattern.pattern}"
            with _EMBEDDING_CACHE_LOCK:
                if pattern_key not in _EMBEDDING_CACHE:
                    if not self._load_model():
                        return False, 0.0
                    _EMBEDDING_CACHE[pattern_key] = self.model.encode(
                        [pattern.pattern],
                        convert_to_tensor=True
                    )
                pattern_embedding = _EMBEDDING_CACHE[pattern_key]

            # Calculate similarity
            similarity = util.pytorch_cos_sim(pattern_embedding, text_embedding)
            score = float(similarity[0][0])

            self.last_error = None
            return score >= pattern.threshold, score

        except Exception as e:
            self.last_error = str(e)
            logger.error(f"Error in semantic matching with embedding: {e}")
            return False, 0.0

    def evaluate(self, pattern: SemanticPattern, text: str) -> Tuple[bool, float]:
        """
        Check if a semantic pattern matches the text based on similarity (thread-safe).

        Args:
            pattern: The SemanticPattern to match
            text: The text to evaluate

        Returns:
            Tuple of (match_success, similarity_score)
        """
        # Input validation - handle None/empty text gracefully
        if text is None or not isinstance(text, str) or not text.strip():
            return False, 0.0

        if not self._load_model():
            return False, 0.0

        try:
            # Import here to avoid dependency issues if not needed
            from sentence_transformers import util

            # Get or compute pattern embedding (thread-safe)
            pattern_key = f"{self.model_name}:{pattern.pattern}"
            with _EMBEDDING_CACHE_LOCK:
                if pattern_key not in _EMBEDDING_CACHE:
                    _EMBEDDING_CACHE[pattern_key] = self.model.encode(
                        [pattern.pattern],
                        convert_to_tensor=True
                    )
                pattern_embedding = _EMBEDDING_CACHE[pattern_key]

            # Get or compute text embedding (thread-safe)
            text_key = f"{self.model_name}:{text}"
            with _TEXT_EMBEDDING_LOCK:
                if text_key not in _TEXT_EMBEDDING_CACHE:
                    _TEXT_EMBEDDING_CACHE[text_key] = self.model.encode([text], convert_to_tensor=True)
                text_embedding = _TEXT_EMBEDDING_CACHE[text_key]

            # Calculate similarity
            similarity = util.pytorch_cos_sim(pattern_embedding, text_embedding)
            score = float(similarity[0][0])

            # Check if similarity is above threshold
            self.last_error = None
            return score >= pattern.threshold, score

        except Exception as e:
            self.last_error = str(e)
            logger.error(f"Error in semantic matching: {e}")
            return False, 0.0
