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

from nova.core.rules import NovaRule, KeywordPattern, SemanticPattern, LLMPattern, FuzzyPattern
from nova.evaluators.keywords import DefaultKeywordEvaluator
from nova.evaluators.condition import evaluate_condition
from nova.utils.logger import get_logger

# Get logger for this module
logger = get_logger("nova.matcher")

# Optional imports - these may not be available if extras not installed
DefaultSemanticEvaluator = None
OpenAIEvaluator = None
LLMEvaluator = None
DefaultFuzzyEvaluator = None 

try:
    from nova.evaluators.semantics import DefaultSemanticEvaluator
except ImportError:
    pass

try:
    from nova.evaluators.llm import OpenAIEvaluator, LLMEvaluator
except ImportError:
    pass

try:
    from nova.evaluators.fuzzy import DefaultFuzzyEvaluator
except ImportError:
    pass


class NovaMatcher:
    """
    Matcher for Nova rules.
    Evaluates text against rules using different pattern types.
    Uses lazy evaluator initialization for better performance.
    """
    
    def __init__(self, 
                 rule: NovaRule,
                 keyword_evaluator: Optional[DefaultKeywordEvaluator] = None,
                 fuzzy_evaluator: Optional[Any] = None,
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

        needs_fuzzy = False
        # Check if rule has fuzzy section (handle attribute safely)
        if rule and rule.fuzzy:
            needs_fuzzy = True
        elif rule and 'fuzzy' in rule.condition.lower():
            needs_fuzzy = True

        # Only initialize semantic evaluator if needed
        if needs_semantic:
            if semantic_evaluator:
                self.semantic_evaluator = semantic_evaluator
            elif DefaultSemanticEvaluator is not None:
                self.semantic_evaluator = DefaultSemanticEvaluator()
            else:
                self.semantic_evaluator = None
                logger.warning("Rule requires semantic evaluation but sentence-transformers not available. Install with: pip install nova-hunting[llm]")
        else:
            self.semantic_evaluator = None
            
        # Handle LLM evaluator initialization
        if llm_evaluator:
            # Use provided evaluator regardless of need
            self.llm_evaluator = llm_evaluator
        elif needs_llm and create_llm_evaluator:
            # Create a new evaluator if needed and allowed to create
            if OpenAIEvaluator is not None:
                self.llm_evaluator = OpenAIEvaluator()
            else:
                self.llm_evaluator = None
                logger.warning("Rule requires LLM evaluation but LLM dependencies not available. Install with: pip install nova-hunting[llm]")
        else:
            # No evaluator provided and either not needed or not allowed to create
            self.llm_evaluator = None
            if needs_llm:
                logger.warning("Rule requires LLM evaluation but no evaluator provided and creation disabled.")
            # Remove the verbose message for rules that don't need LLM evaluation

        if fuzzy_evaluator:
            self.fuzzy_evaluator = fuzzy_evaluator
        elif needs_fuzzy:
            if DefaultFuzzyEvaluator is not None:
                self.fuzzy_evaluator = DefaultFuzzyEvaluator()
            else:
                self.fuzzy_evaluator = None
                logger.warning("Rule requires fuzzy evaluation but rapidfuzz not available.")
        else:
            self.fuzzy_evaluator = None
        
        
        # Pre-compile keyword patterns for performance
        if rule:
            self._precompile_patterns()

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
            'fuzzy': set(),      # Track which keywords need fuzzy evaluation
            'semantics': set(),
            'llm': set(),
            'section_wildcards': set()
        }
        
        # 1. Check for section wildcards (e.g., keywords.*, fuzzy.*)
        for section in ['keywords', 'semantics', 'llm', 'fuzzy']:
            if f"{section}.*" in condition:
                needed_patterns['section_wildcards'].add(section)
                
        # 2. Check for "any of" section wildcards
        for section in ['keywords', 'semantics', 'llm', 'fuzzy']:
            if f"any of {section}.*" in condition:
                needed_patterns['section_wildcards'].add(section)

        # 3. Check for direct variable references with section prefixes (e.g., fuzzy.$var)
        for section in ['keywords', 'semantics', 'llm', 'fuzzy']:
            # Exact references: "section.$var"
            pattern = rf'{section}\.\$([a-zA-Z0-9_]+)(?!\*)'
            for match in re.finditer(pattern, condition):
                var_name = f"${match.group(1)}"
                needed_patterns[section].add(var_name)
                
            # Wildcard references: "section.$var*"
            wildcard_pattern = rf'{section}\.\$([a-zA-Z0-9_]+)\*'
            for match in re.finditer(wildcard_pattern, condition):
                prefix = match.group(1)
                
                # REDIRECT: If the condition asks for 'fuzzy.', we look for the data in 'keywords'
                if section == 'fuzzy':
                    search_in = self.rule.keywords
                else:
                    search_in = getattr(self.rule, section, {})
                
                # Add all matching variables to needed patterns
                for var_name in search_in:
                    if var_name[1:].startswith(prefix):  # Remove $ from var name
                        needed_patterns[section].add(var_name)
        
        # 4. Check for standalone variables ($var)
        var_pattern = r'(?<![a-zA-Z0-9_\.])(\$[a-zA-Z0-9_]+)(?!\*)'
        for match in re.finditer(var_pattern, condition):
            var_name = match.group(1)
            
            # Standalone variables default to their respective sections.
            # We removed the 'elif var_name in self.rule.fuzzy' block 
            # because 'fuzzy' is now an attribute of 'keywords'.
            if var_name in self.rule.keywords:
                needed_patterns['keywords'].add(var_name)
            elif var_name in self.rule.semantics:
                needed_patterns['semantics'].add(var_name)
            elif var_name in self.rule.llms:
                needed_patterns['llm'].add(var_name)
        
        # 5. Check for "any of" wildcards (e.g., any of ($prefix*))
        any_of_pattern = r'any\s+of\s+\(\$([a-zA-Z0-9_]+)\*\)'
        for match in re.finditer(any_of_pattern, condition):
            prefix = match.group(1)
            
            # We removed 'fuzzy' from this list because the data is in 'keywords'
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
        
        Args:
            prompt: The prompt text to check
            
        Returns:
            Dictionary containing match results and details
        """
        # Extract variables needed based on the condition
        condition = self.rule.condition
        needed_patterns = self._analyze_condition(condition)
        
        # Track all evaluation results for debugging
        all_keyword_matches = {}
        all_fuzzy_matches = {}
        all_semantic_matches = {}
        all_semantic_scores = {}
        all_llm_matches = {}
        all_llm_scores = {}
        
        # Dictionary to hold evaluation functions for lazy evaluation
        lazy_evaluations = {}
        
        # Initialize filtered dictionaries to hold results needed for condition evaluation
        keyword_matches = {}
        fuzzy_matches = {}
        semantic_matches = {}
        llm_matches = {}
        
        # ------ LAZY PATTERN EVALUATION ------
        
        # Set up lazy evaluation functions for keywords
        for key, pattern in self.rule.keywords.items():
            # Only include if explicitly needed by condition or section wildcard is used
            if key in needed_patterns['keywords'] or 'keywords' in needed_patterns['section_wildcards']:
                lazy_evaluations[('keywords', key)] = lambda p=pattern, k=key: self.keyword_evaluator.evaluate(p, prompt, k)
        
        # Set up lazy evaluation functions for semantics (if evaluator exists)
        if self.semantic_evaluator:
            for key, pattern in self.rule.semantics.items():
                # Only include if explicitly needed by condition or section wildcard is used
                if key in needed_patterns['semantics'] or 'semantics' in needed_patterns['section_wildcards']:
                    lazy_evaluations[('semantics', key)] = lambda p=pattern: self.semantic_evaluator.evaluate(p, prompt)
        
        # Set up lazy evaluation functions for LLMs (if evaluator exists)
        if self.llm_evaluator:
            for key, pattern in self.rule.llms.items():
                # Only include if explicitly needed by condition or section wildcard is used
                if key in needed_patterns['llm'] or 'llm' in needed_patterns['section_wildcards']:
                    temperature = pattern.threshold
                    lazy_evaluations[('llm', key)] = lambda p=pattern, t=temperature: self.llm_evaluator.evaluate_prompt(p.pattern, prompt, temperature=t)
        
        if self.fuzzy_evaluator:
            for var_name in needed_patterns['fuzzy']:
                pattern_obj = self.rule.keywords.get(var_name)
                if pattern_obj:
                    lazy_evaluations[('fuzzy', var_name)] = lambda p=pattern_obj, k=var_name:self.fuzzy_evaluator.evaluate(p, prompt, key=k)

        # First evaluate only the patterns that are directly referenced in the condition
        # Create a list of sections and variables to evaluate based on what evaluators are available
        patterns_to_evaluate = [('keywords', name) for name in needed_patterns['keywords']]
        
        if self.semantic_evaluator:
            patterns_to_evaluate += [('semantics', name) for name in needed_patterns['semantics']]
            
        if self.llm_evaluator:
            patterns_to_evaluate += [('llm', name) for name in needed_patterns['llm']]
        
        if self.fuzzy_evaluator:
            patterns_to_evaluate += [('fuzzy', name) for name in needed_patterns['fuzzy']]
            
        # Evaluate each pattern
        for section, var_name in patterns_to_evaluate:
            eval_key = (section, var_name)
            if eval_key in lazy_evaluations:
                try:
                    if section == 'keywords':
                        result = lazy_evaluations[eval_key]()
                        all_keyword_matches[var_name] = result
                        keyword_matches[var_name] = result
                    elif section == 'semantics':
                        matched, score = lazy_evaluations[eval_key]()
                        all_semantic_matches[var_name] = matched
                        all_semantic_scores[var_name] = score
                        semantic_matches[var_name] = matched
                    elif section == 'llm':
                        matched, confidence, details = lazy_evaluations[eval_key]()
                        all_llm_matches[var_name] = matched
                        all_llm_scores[var_name] = confidence
                        llm_matches[var_name] = matched
                    elif section == 'fuzzy':
                        matched = lazy_evaluations[eval_key]()
                        all_fuzzy_matches[var_name] = matched
                        fuzzy_matches[var_name] = matched
                except Exception as e:
                    logger.error(f"Error evaluating {section}.{var_name}: {str(e)}")
                    # Default to False on error
                    if section == 'keywords':
                        all_keyword_matches[var_name] = False
                        keyword_matches[var_name] = False
                    elif section == 'semantics':
                        all_semantic_matches[var_name] = False
                        all_semantic_scores[var_name] = 0.0
                        semantic_matches[var_name] = False
                    elif section == 'llm':
                        all_llm_matches[var_name] = False
                        all_llm_scores[var_name] = 0.0
                        llm_matches[var_name] = False
                    elif section == 'fuzzy':
                        all_fuzzy_matches[var_name] = False
                        fuzzy_matches[var_name] = False
        
        # Process section wildcards if needed
        for section in needed_patterns['section_wildcards']:
            if section == 'keywords' and not all_keyword_matches:
                # Only evaluate all keywords if needed and not already evaluated
                for key, pattern in self.rule.keywords.items():
                    if key not in all_keyword_matches:
                        try:
                            result = self.keyword_evaluator.evaluate(pattern, prompt, key)
                            all_keyword_matches[key] = result
                        except Exception:
                            all_keyword_matches[key] = False
            
            elif section == 'semantics' and self.semantic_evaluator and not all_semantic_matches:
                # Only evaluate all semantics if needed and not already evaluated
                for key, pattern in self.rule.semantics.items():
                    if key not in all_semantic_matches:
                        try:
                            matched, score = self.semantic_evaluator.evaluate(pattern, prompt)
                            all_semantic_matches[key] = matched
                            all_semantic_scores[key] = score
                        except Exception:
                            all_semantic_matches[key] = False
                            all_semantic_scores[key] = 0.0
            
            elif section == 'llm' and self.llm_evaluator and not all_llm_matches:
                # Only evaluate all LLM patterns if needed and not already evaluated
                for key, pattern in self.rule.llms.items():
                    if key not in all_llm_matches:
                        try:
                            temperature = pattern.threshold
                            matched, confidence, details = self.llm_evaluator.evaluate_prompt(pattern.pattern, prompt, temperature=temperature)
                            all_llm_matches[key] = matched
                            all_llm_scores[key] = confidence
                        except Exception:
                            all_llm_matches[key] = False
                            all_llm_scores[key] = 0.0
            elif section == 'fuzzy' and self.fuzzy_evaluator:
                # Proactively scan all keywords marked as fuzzy for the fuzzy.* wildcard
                for key, pattern in self.rule.keywords.items():
                    # Only process keywords the user marked with the 'fuzzy' keyword
                    if getattr(pattern, 'is_fuzzy', False):
                        if key not in all_fuzzy_matches:
                            try:
                                result = self.fuzzy_evaluator.evaluate(pattern, prompt, key=key)
                                all_fuzzy_matches[key] = result
                                # We must put the result in fuzzy_matches for the condition evaluator
                                fuzzy_matches[key] = result 
                            except Exception:
                                all_fuzzy_matches[key] = False
                                fuzzy_matches[key] = False
                        else:
                            # If already evaluated by a direct reference earlier, 
                            # ensure it's copied into the condition dict
                            fuzzy_matches[key] = all_fuzzy_matches[key]
        
        # Evaluate condition if provided
        has_match = False
        condition_result = None
        
        if condition:
            # Make sure eval_condition gets all variables that might be needed by wildcards
            if 'keywords' in needed_patterns['section_wildcards']:
                keyword_matches.update(all_keyword_matches)
            if 'semantics' in needed_patterns['section_wildcards'] and self.semantic_evaluator:
                semantic_matches.update(all_semantic_matches)
            if 'llm' in needed_patterns['section_wildcards'] and self.llm_evaluator:
                llm_matches.update(all_llm_matches)
            if 'fuzzy' in needed_patterns['section_wildcards'] and self.fuzzy_evaluator:
                fuzzy_matches.update(all_fuzzy_matches)
                
            # Use the condition evaluator with filtered match types
            condition_result = evaluate_condition(
                condition, 
                keyword_matches,
                semantic_matches, 
                llm_matches,
                fuzzy_matches
            )
            has_match = condition_result
        else:
            # Fall back to original behavior if no condition is specified
            has_match = any(keyword_matches.values()) or any(semantic_matches.values()) or any(llm_matches.values())
        
        # Build results with matching variables only
        results = {
            'matched': has_match,
            'rule_name': self.rule.name,
            'meta': self.rule.meta,
            'matching_keywords': {k: v for k, v in keyword_matches.items() if v},
            'matching_semantics': {k: v for k, v in semantic_matches.items() if v},
            'matching_llm': {k: v for k, v in llm_matches.items() if v},
            'matching_fuzzy': {k: v for k, v in fuzzy_matches.items() if v},
            'semantic_scores': all_semantic_scores,
            'llm_scores': all_llm_scores,
            'debug': {
                'condition': condition,
                'condition_result': condition_result,
                'all_keyword_matches': all_keyword_matches,
                'all_semantic_matches': all_semantic_matches,
                'all_llm_matches': all_llm_matches,
                'all_fuzzy_matches': all_fuzzy_matches
            }
        }
        
        return results