"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia
twitter: @fr0gger_
License: MIT License
Version: 1.0.0
Description: Core matcher implementation for Nova rules
"""

from typing import Dict, List, Tuple, Optional, Any, Set, Callable
import re

from nova.core.rules import NovaRule, KeywordPattern, SemanticPattern, LLMPattern
from nova.evaluators.keywords import DefaultKeywordEvaluator
from nova.evaluators.condition import (
    evaluate_condition,
    can_semantics_change_outcome,
    can_llm_change_outcome
)
from nova.utils.logger import get_logger

# Get logger for this module
logger = get_logger("nova.matcher")

# Lazy-loaded module references - avoids expensive imports at module load time
_DefaultSemanticEvaluator = None
_OpenAIEvaluator = None
_LLMEvaluator = None
_imports_attempted = {'semantic': False, 'llm': False}


def _get_semantic_evaluator_class():
    """Lazy import of DefaultSemanticEvaluator - only loads when actually needed."""
    global _DefaultSemanticEvaluator, _imports_attempted
    if not _imports_attempted['semantic']:
        _imports_attempted['semantic'] = True
        try:
            from nova.evaluators.semantics import DefaultSemanticEvaluator
            _DefaultSemanticEvaluator = DefaultSemanticEvaluator
        except ImportError:
            pass
    return _DefaultSemanticEvaluator


def _get_llm_evaluator_classes():
    """Lazy import of LLM evaluators - only loads when actually needed."""
    global _OpenAIEvaluator, _LLMEvaluator, _imports_attempted
    if not _imports_attempted['llm']:
        _imports_attempted['llm'] = True
        try:
            from nova.evaluators.llm import OpenAIEvaluator, LLMEvaluator
            _OpenAIEvaluator = OpenAIEvaluator
            _LLMEvaluator = LLMEvaluator
        except ImportError:
            pass
    return _OpenAIEvaluator, _LLMEvaluator


class NovaMatcher:
    """
    Matcher for Nova rules.
    Evaluates text against rules using different pattern types.
    Uses lazy evaluator initialization for better performance.
    """
    
    def __init__(self, 
                 rule: NovaRule,
                 keyword_evaluator: Optional[DefaultKeywordEvaluator] = None,
                 semantic_evaluator: Optional[Any] = None,  # DefaultSemanticEvaluator might not be available
                 llm_evaluator: Optional[Any] = None,       # LLMEvaluator might not be available
                 create_llm_evaluator: bool = True):
        """
        Initialize the matcher with a rule and optional custom evaluators.
        Only initializes evaluators when needed based on rule content.
        
        Args:
            rule: The NovaRule to match against
            keyword_evaluator: Custom keyword evaluator (uses DefaultKeywordEvaluator if None)
            semantic_evaluator: Custom semantic evaluator (uses DefaultSemanticEvaluator if None)
            llm_evaluator: Custom LLM evaluator (uses OpenAIEvaluator if None)
            create_llm_evaluator: Whether to create a new LLM evaluator if needed and none is provided.
                                  If False, and llm_evaluator is None, no LLM evaluations will be performed.
        """
        self.rule = rule
        
        # Always initialize keyword evaluator since it's lightweight
        self.keyword_evaluator = keyword_evaluator or DefaultKeywordEvaluator()
        
        # Check if semantic evaluator is needed
        needs_semantic = False
        if rule and rule.semantics:
            needs_semantic = True
        elif rule and 'semantics' in rule.condition.lower():
            needs_semantic = True
            
        # Check if LLM evaluator is needed
        needs_llm = False
        if rule and rule.llms:
            needs_llm = True
        elif rule and 'llm.' in rule.condition.lower():
            needs_llm = True
        
        # Only initialize semantic evaluator if needed
        if needs_semantic:
            if semantic_evaluator:
                self.semantic_evaluator = semantic_evaluator
            else:
                # Lazy import - only load the module when actually needed
                SemanticEvalClass = _get_semantic_evaluator_class()
                if SemanticEvalClass is not None:
                    self.semantic_evaluator = SemanticEvalClass()
                else:
                    self.semantic_evaluator = None
                    logger.warning("Rule requires semantic evaluation but sentence-transformers not available. Install with: pip install nova-hunting")
        else:
            self.semantic_evaluator = None

        # Handle LLM evaluator initialization
        if llm_evaluator:
            # Use provided evaluator regardless of need
            self.llm_evaluator = llm_evaluator
        elif needs_llm and create_llm_evaluator:
            # Lazy import - only load the module when actually needed
            OpenAIEval, _ = _get_llm_evaluator_classes()
            if OpenAIEval is not None:
                self.llm_evaluator = OpenAIEval()
            else:
                self.llm_evaluator = None
                logger.warning("Rule requires LLM evaluation but LLM dependencies not available. Install with: pip install nova-hunting")
        else:
            # No evaluator provided and either not needed or not allowed to create
            self.llm_evaluator = None
            if needs_llm:
                logger.warning("Rule requires LLM evaluation but no evaluator provided and creation disabled.")
        
        # Pre-compile keyword patterns for performance
        if rule:
            self._precompile_patterns()
            # Pre-compute condition analysis (static for rule's lifetime)
            self._cached_needed_patterns = self._analyze_condition(rule.condition)
        else:
            self._cached_needed_patterns = None

    def _precompile_patterns(self):
        """Pre-compile regex patterns for better performance."""
        if not self.rule:
            return
            
        for key, pattern in self.rule.keywords.items():
            if pattern.is_regex:
                self.keyword_evaluator.compile_pattern(key, pattern)

    def set_rule(self, rule: NovaRule):
        """
        Update the matcher with a new rule.
        This is more efficient than creating a new matcher instance.

        Args:
            rule: The new NovaRule to match against
        """
        self.rule = rule
        self._precompile_patterns()
        # Update cached condition analysis for new rule
        if rule:
            self._cached_needed_patterns = self._analyze_condition(rule.condition)
        else:
            self._cached_needed_patterns = None
    
    def _analyze_condition(self, condition: str) -> Dict[str, Set[str]]:
        """
        Analyze the rule condition to determine which patterns need to be evaluated.
        
        Args:
            condition: The rule condition
            
        Returns:
            Dictionary with sets of variable names needed for each pattern type
        """
        needed_patterns = {
            'keywords': set(),
            'semantics': set(),
            'llm': set(),
            'section_wildcards': set()
        }
        
        # Check for section wildcards
        for section in ['keywords', 'semantics', 'llm']:
            if f"{section}.*" in condition:
                needed_patterns['section_wildcards'].add(section)
                
        # Check for "any of" section wildcards
        for section in ['keywords', 'semantics', 'llm']:
            if f"any of {section}.*" in condition:
                needed_patterns['section_wildcards'].add(section)

        # Check for direct variable references with section prefixes
        for section in ['keywords', 'semantics', 'llm']:
            # Exact references: "section.$var"
            pattern = rf'{section}\.\$([a-zA-Z0-9_]+)(?!\*)'
            for match in re.finditer(pattern, condition):
                var_name = f"${match.group(1)}"
                needed_patterns[section].add(var_name)
                
            # Wildcard references: "section.$var*"
            wildcard_pattern = rf'{section}\.\$([a-zA-Z0-9_]+)\*'
            for match in re.finditer(wildcard_pattern, condition):
                prefix = match.group(1)
                # Add all matching variables to needed patterns
                for var_name in getattr(self.rule, section, {}):
                    if var_name[1:].startswith(prefix):  # Remove $ from var name
                        needed_patterns[section].add(var_name)
        
        # Check for standalone variables ($var)
        var_pattern = r'(?<![a-zA-Z0-9_\.])(\$[a-zA-Z0-9_]+)(?!\*)'
        for match in re.finditer(var_pattern, condition):
            var_name = match.group(1)
            
            # Determine which section this variable belongs to
            if var_name in self.rule.keywords:
                needed_patterns['keywords'].add(var_name)
            elif var_name in self.rule.semantics:
                needed_patterns['semantics'].add(var_name)
            elif var_name in self.rule.llms:
                needed_patterns['llm'].add(var_name)
        
        # Check for "any of" wildcards
        any_of_pattern = r'any\s+of\s+\(\$([a-zA-Z0-9_]+)\*\)'
        for match in re.finditer(any_of_pattern, condition):
            prefix = match.group(1)
            
            # Add all matching variables from all sections
            for section, patterns in [
                ('keywords', self.rule.keywords),
                ('semantics', self.rule.semantics),
                ('llm', self.rule.llms)
            ]:
                for var_name in patterns:
                    if var_name[1:].startswith(prefix):
                        needed_patterns[section].add(var_name)
        
        return needed_patterns
        
    def check_prompt(self, prompt: str) -> Dict[str, Any]:
        """
        Check if a prompt matches the rule.

        Uses short-circuit evaluation: evaluates patterns in order of cost
        (keywords → semantics → LLM) and stops as soon as condition is satisfied.

        Args:
            prompt: The prompt text to check

        Returns:
            Dictionary containing match results and details
        """
        # Use cached condition analysis (pre-computed at initialization)
        condition = self.rule.condition
        needed_patterns = self._cached_needed_patterns or self._analyze_condition(condition)

        # Track all evaluation results for debugging
        all_keyword_matches = {}
        all_semantic_matches = {}
        all_semantic_scores = {}
        all_llm_matches = {}
        all_llm_scores = {}
        all_llm_details = {}

        # Initialize filtered dictionaries to hold results needed for condition evaluation
        keyword_matches = {}
        semantic_matches = {}
        llm_matches = {}

        # Helper function to build final results
        def build_results(has_match: bool, condition_result: Any) -> Dict[str, Any]:
            return {
                'matched': has_match,
                'rule_name': self.rule.name,
                'meta': self.rule.meta,
                'matching_keywords': {k: v for k, v in keyword_matches.items() if v},
                'matching_semantics': {k: v for k, v in semantic_matches.items() if v},
                'matching_llm': {k: v for k, v in llm_matches.items() if v},
                'semantic_scores': all_semantic_scores,
                'llm_scores': all_llm_scores,
                'debug': {
                    'condition': condition,
                    'condition_result': condition_result,
                    'all_keyword_matches': all_keyword_matches,
                    'all_semantic_matches': all_semantic_matches,
                    'all_llm_matches': all_llm_matches,
                    'all_llm_details': all_llm_details
                }
            }

        # ------ STAGE 1: EVALUATE KEYWORDS (fastest) ------

        # Evaluate keywords needed by condition or section wildcards
        for key, pattern in self.rule.keywords.items():
            if key in needed_patterns['keywords'] or 'keywords' in needed_patterns['section_wildcards']:
                try:
                    result = self.keyword_evaluator.evaluate(pattern, prompt, key)
                    all_keyword_matches[key] = result
                    keyword_matches[key] = result
                except Exception as e:
                    logger.error(f"Error evaluating keywords.{key}: {str(e)}")
                    all_keyword_matches[key] = False
                    keyword_matches[key] = False

        # Update keyword_matches for wildcards
        if 'keywords' in needed_patterns['section_wildcards']:
            keyword_matches.update(all_keyword_matches)

        # SHORT-CIRCUIT CHECK: Try to evaluate condition with just keywords
        # If condition is satisfied (e.g., OR condition with keyword match), skip expensive evaluations
        if condition:
            try:
                early_result = evaluate_condition(condition, keyword_matches, {}, {})
                if early_result:
                    # Condition satisfied with just keywords - no need for semantic/LLM
                    return build_results(True, early_result)
            except Exception:
                # Can't determine yet, continue with more patterns
                pass

        # ------ STAGE 2: EVALUATE SEMANTICS (medium cost) ------

        # Check if semantics could possibly change the outcome before running expensive evaluation
        skip_semantics = False
        if condition and not can_semantics_change_outcome(condition, keyword_matches):
            # Semantics can't change the outcome - skip this evaluation stage
            skip_semantics = True
            logger.debug(f"Skipping semantic evaluation for rule '{self.rule.name}' - can't change outcome")

        if self.semantic_evaluator and not skip_semantics:
            for key, pattern in self.rule.semantics.items():
                if key in needed_patterns['semantics'] or 'semantics' in needed_patterns['section_wildcards']:
                    try:
                        matched, score = self.semantic_evaluator.evaluate(pattern, prompt)
                        all_semantic_matches[key] = matched
                        all_semantic_scores[key] = score
                        semantic_matches[key] = matched
                    except Exception as e:
                        logger.error(f"Error evaluating semantics.{key}: {str(e)}")
                        all_semantic_matches[key] = False
                        all_semantic_scores[key] = 0.0
                        semantic_matches[key] = False

            # Update semantic_matches for wildcards
            if 'semantics' in needed_patterns['section_wildcards']:
                semantic_matches.update(all_semantic_matches)

            # SHORT-CIRCUIT CHECK: Try with keywords + semantics
            if condition:
                try:
                    early_result = evaluate_condition(condition, keyword_matches, semantic_matches, {})
                    if early_result:
                        # Condition satisfied - no need for expensive LLM evaluation
                        return build_results(True, early_result)
                except Exception:
                    # Can't determine yet, continue
                    pass

        # ------ STAGE 3: EVALUATE LLM PATTERNS (most expensive) ------

        # Check if LLM could possibly change the outcome before running expensive API calls
        skip_llm = False
        if condition and not can_llm_change_outcome(condition, keyword_matches, semantic_matches):
            # LLM can't change the outcome - skip this evaluation stage
            skip_llm = True
            logger.debug(f"Skipping LLM evaluation for rule '{self.rule.name}' - can't change outcome")

        if self.llm_evaluator and not skip_llm:
            for key, pattern in self.rule.llms.items():
                if key in needed_patterns['llm'] or 'llm' in needed_patterns['section_wildcards']:
                    try:
                        # Note: pattern.threshold is used as LLM temperature (0.0=deterministic, 1.0=creative)
                        # The LLM itself determines if the pattern matches; threshold controls response variability
                        llm_temperature = pattern.threshold
                        matched, confidence, details = self.llm_evaluator.evaluate_prompt(
                            pattern.pattern, prompt, temperature=llm_temperature
                        )
                        all_llm_matches[key] = matched
                        all_llm_scores[key] = confidence
                        llm_matches[key] = matched
                        all_llm_details[key] = details
                    except Exception as e:
                        logger.error(f"Error evaluating llm.{key}: {str(e)}")
                        all_llm_matches[key] = False
                        all_llm_scores[key] = 0.0
                        llm_matches[key] = False

                        all_llm_details[key] = {
                            "error": str(e),
                            "evaluator_type": "unknown",
                        }
            # Update llm_matches for wildcards
            if 'llm' in needed_patterns['section_wildcards']:
                llm_matches.update(all_llm_matches)

        # ------ FINAL CONDITION EVALUATION ------

        has_match = False
        condition_result = None

        if condition:
            # Final evaluation with all pattern results
            condition_result = evaluate_condition(
                condition,
                keyword_matches,
                semantic_matches,
                llm_matches
            )
            has_match = condition_result
        else:
            # Fall back to original behavior if no condition is specified
            has_match = any(keyword_matches.values()) or any(semantic_matches.values()) or any(llm_matches.values())

        return build_results(has_match, condition_result)