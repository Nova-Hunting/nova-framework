"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia 
twitter: @fr0gger_
License: MIT License
Version: see nova._version
Description: Condition evaluator for Nova rules with improved error handling
"""

import ast
from itertools import product
from typing import Dict, Set
import re
from nova.utils.logger import get_logger

# Get logger for this module
logger = get_logger("nova.evaluators.condition")


def _truthy_count(matches: Dict[str, bool]) -> int:
    return sum(1 for value in matches.values() if bool(value))


def _quantifier_result(quantifier: str, total_count: int, truthy_count: int) -> bool:
    quantifier = quantifier.lower()
    if quantifier == "any":
        return truthy_count > 0
    if quantifier == "all":
        return total_count > 0 and truthy_count == total_count
    return truthy_count >= int(quantifier)


def _section_matches(
    section: str,
    keyword_matches: Dict[str, bool],
    semantic_matches: Dict[str, bool],
    llm_matches: Dict[str, bool],
) -> Dict[str, bool]:
    return {
        "keywords": keyword_matches,
        "semantics": semantic_matches,
        "llm": llm_matches,
    }.get(section.lower(), {})


def _prefix_matches(prefix: str, *match_dicts: Dict[str, bool]) -> Dict[str, bool]:
    matches = {}
    for match_dict in match_dicts:
        for variable, value in match_dict.items():
            if variable.startswith("$") and variable[1:].startswith(prefix):
                matches[variable] = value
    return matches


def _safe_eval_boolean_expression(expression: str) -> bool:
    """Evaluate a normalized boolean expression without Python eval."""
    tree = ast.parse(expression, mode="eval")

    def evaluate_node(node: ast.AST) -> bool:
        if isinstance(node, ast.Expression):
            return evaluate_node(node.body)

        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return node.value
            raise ValueError(f"Unsupported constant in condition: {node.value!r}")

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not evaluate_node(node.operand)

        if isinstance(node, ast.BoolOp):
            values = [evaluate_node(value) for value in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)

        raise ValueError(f"Unsupported expression in condition: {ast.dump(node, include_attributes=False)}")

    return evaluate_node(tree)


def evaluate_condition(condition: str, keyword_matches: Dict[str, bool], 
                       semantic_matches: Dict[str, bool], llm_matches: Dict[str, bool] = None) -> bool:
    """
    Evaluate a condition expression against pattern match results.
    Handles wildcards correctly with improved parsing for complex expressions.
    
    Args:
        condition: Condition expression to evaluate
        keyword_matches: Dictionary of keyword match results
        semantic_matches: Dictionary of semantic match results
        llm_matches: Dictionary of LLM match results (optional)
        
    Returns:
        Boolean indicating whether the condition is satisfied
    """
    # Handle empty or missing condition
    if not condition or condition.strip() == '':
        return False
    
    # Initialize llm_matches if not provided
    if llm_matches is None:
        llm_matches = {}
    
    # Make a copy of the original condition for debugging
    original_condition = condition
    
    # Create a working copy of the condition for evaluation
    eval_condition = condition.strip()
    
    # Check for unbalanced parentheses before proceeding
    if eval_condition.count('(') != eval_condition.count(')'):
        logger.warning(f"Unbalanced parentheses in condition: {eval_condition}")
        return False
    
    # Quantifiers must run before raw wildcards so "2 of keywords.*" is not
    # partially converted as "2 of True".
    def replace_cross_section_prefix_quantifier(match: re.Match) -> str:
        quantifier = match.group(1)
        prefix = match.group(2)
        matches = _prefix_matches(prefix, keyword_matches, semantic_matches, llm_matches)
        result = _quantifier_result(quantifier, len(matches), _truthy_count(matches))
        return "True" if result else "False"

    eval_condition = re.sub(
        r'\b(any|all|\d+)\s+of\s+\(\$([a-zA-Z0-9_]+)\*\)',
        replace_cross_section_prefix_quantifier,
        eval_condition,
        flags=re.IGNORECASE,
    )

    def replace_section_prefix_quantifier(match: re.Match) -> str:
        quantifier = match.group(1)
        section = match.group(2)
        prefix = match.group(3)
        matches = _prefix_matches(
            prefix,
            _section_matches(section, keyword_matches, semantic_matches, llm_matches),
        )
        result = _quantifier_result(quantifier, len(matches), _truthy_count(matches))
        return "True" if result else "False"

    eval_condition = re.sub(
        r'\b(any|all|\d+)\s+of\s+(keywords|semantics|llm)\.\$([a-zA-Z0-9_]+)\*',
        replace_section_prefix_quantifier,
        eval_condition,
        flags=re.IGNORECASE,
    )

    def replace_section_quantifier(match: re.Match) -> str:
        quantifier = match.group(1)
        section = match.group(2)
        matches = _section_matches(section, keyword_matches, semantic_matches, llm_matches)
        result = _quantifier_result(quantifier, len(matches), _truthy_count(matches))
        return "True" if result else "False"

    eval_condition = re.sub(
        r'\b(any|all|\d+)\s+of\s+(keywords|semantics|llm)(?:\.\*)?',
        replace_section_quantifier,
        eval_condition,
        flags=re.IGNORECASE,
    )

    # Handle raw section-specific prefix wildcards as "any of this prefix".
    def replace_section_prefix(match: re.Match) -> str:
        section = match.group(1)
        prefix = match.group(2)
        matches = _prefix_matches(
            prefix,
            _section_matches(section, keyword_matches, semantic_matches, llm_matches),
        )
        return "True" if _truthy_count(matches) > 0 else "False"

    eval_condition = re.sub(
        r'(keywords|semantics|llm)\.\$([a-zA-Z0-9_]+)\*',
        replace_section_prefix,
        eval_condition,
        flags=re.IGNORECASE,
    )

    # Handle section wildcards (e.g., "keywords.*") - runs after "N of" to avoid conflicts
    if "keywords.*" in eval_condition:
        any_keyword = any(bool(value) for value in keyword_matches.values())
        eval_condition = eval_condition.replace("keywords.*", "True" if any_keyword else "False")

    if "semantics.*" in eval_condition:
        any_semantic = any(bool(value) for value in semantic_matches.values())
        eval_condition = eval_condition.replace("semantics.*", "True" if any_semantic else "False")

    if "llm.*" in eval_condition:
        any_llm = any(bool(value) for value in llm_matches.values())
        eval_condition = eval_condition.replace("llm.*", "True" if any_llm else "False")
    
    # Process direct variable references to boolean values
    # Handle different formats: "section.$var", "$var"
    
    # First, handle fully qualified variables (section.$var)
    section_var_pattern = r'(keywords|semantics|llm)\.\$([a-zA-Z0-9_]+)(?![a-zA-Z0-9_]*\*)'

    def replace_section_variable(match: re.Match) -> str:
        section = match.group(1)
        var_name = "$" + match.group(2)
        
        # Determine the match value
        match_value = False
        if section == "keywords" and var_name in keyword_matches:
            match_value = keyword_matches[var_name]
        elif section == "semantics" and var_name in semantic_matches:
            match_value = semantic_matches[var_name]
        elif section == "llm" and var_name in llm_matches:
            match_value = llm_matches[var_name]
            
        return "True" if match_value else "False"

    eval_condition = re.sub(section_var_pattern, replace_section_variable, eval_condition)
    
    # Then handle standalone variables ($var)
    standalone_var_pattern = r'(?<![a-zA-Z0-9_\.\$])(\$[a-zA-Z0-9_]+)(?![a-zA-Z0-9_\*])'

    def replace_standalone_variable(match: re.Match) -> str:
        var_name = match.group(1)
        
        # Find where this variable is defined
        match_value = False
        if var_name in keyword_matches:
            match_value = keyword_matches[var_name]
        elif var_name in semantic_matches:
            match_value = semantic_matches[var_name]
        elif var_name in llm_matches:
            match_value = llm_matches[var_name]
            
        return "True" if match_value else "False"

    eval_condition = re.sub(standalone_var_pattern, replace_standalone_variable, eval_condition)
    
    # Standardize logical operators to Python syntax
    eval_condition = re.sub(r'\band\b', 'and', eval_condition, flags=re.IGNORECASE)
    eval_condition = re.sub(r'\bor\b', 'or', eval_condition, flags=re.IGNORECASE)
    eval_condition = re.sub(r'\bnot\b', 'not', eval_condition, flags=re.IGNORECASE)
    
    # Clean up and normalize the expression syntax
    eval_condition = re.sub(r'\s+', ' ', eval_condition).strip()
    
    # Ensure parentheses are properly spaced for evaluation
    eval_condition = re.sub(r'\(\s+', '(', eval_condition)
    eval_condition = re.sub(r'\s+\)', ')', eval_condition)
    
    # Ensure no extra spaces around operators
    eval_condition = re.sub(r'\s+and\s+', ' and ', eval_condition)
    eval_condition = re.sub(r'\s+or\s+', ' or ', eval_condition)
    eval_condition = re.sub(r'\s+not\s+', ' not ', eval_condition)
    
    # Replace True/False strings with proper booleans, handling case sensitivity
    eval_condition = re.sub(r'\bTrue\b', 'True', eval_condition)
    eval_condition = re.sub(r'\bFalse\b', 'False', eval_condition)
    eval_condition = re.sub(r'\btrue\b', 'True', eval_condition)
    eval_condition = re.sub(r'\bfalse\b', 'False', eval_condition)
    
    try:
        result = _safe_eval_boolean_expression(eval_condition)
        return bool(result)
    except Exception:
        # Special case handling for common patterns that might fail normalization
        
        # If the condition is just a single section.$ reference and there's a match
        if re.match(r'^(keywords|semantics|llm)\.\$[a-zA-Z0-9_]+$', original_condition):
            try:
                section, var = original_condition.split('.')
                if section == "keywords" and var in keyword_matches:
                    return keyword_matches[var]
                elif section == "semantics" and var in semantic_matches:
                    return semantic_matches[var]
                elif section == "llm" and var in llm_matches:
                    return llm_matches[var]
            except Exception:
                # If any error occurs in this special case handling, continue to the next one
                pass
        
        # Handle cross-section references like "$keyword1 and semantics.$semantic1"
        if " and " in original_condition:
            try:
                parts = original_condition.split(" and ")
                results = []
                recognized_all_parts = True
                
                for part in parts:
                    part = part.strip()
                    if part.startswith("semantics.$"):
                        var = part.replace("semantics.", "")
                        results.append(semantic_matches.get(var, False))
                    elif part.startswith("keywords.$"):
                        var = part.replace("keywords.", "")
                        results.append(keyword_matches.get(var, False))
                    elif part.startswith("llm.$"):
                        var = part.replace("llm.", "")
                        results.append(llm_matches.get(var, False))
                    elif part.startswith("$"):
                        if part in keyword_matches:
                            results.append(keyword_matches[part])
                        elif part in semantic_matches:
                            results.append(semantic_matches[part])
                        elif part in llm_matches:
                            results.append(llm_matches[part])
                        else:
                            results.append(False)
                    else:
                        recognized_all_parts = False
                        break
                
                # If all parts are True, return True
                if recognized_all_parts and len(results) == len(parts):
                    return all(results)
            except Exception:
                # If any error occurs in this special case handling, continue to next fallback
                pass
        
        # If we reach here, something went wrong with the evaluation.
        logger.warning(f"Condition evaluation failed for: {original_condition}")
        return False


def _standalone_variables(condition: str) -> Set[str]:
    """Return unqualified variable references such as $foo."""
    return {
        match.group(1)
        for match in re.finditer(r'(?<![a-zA-Z0-9_\.\$])(\$[a-zA-Z0-9_]+)(?![a-zA-Z0-9_\*])', condition)
    }


def _candidate_section_variables(
    condition: str,
    section: str,
    known_standalone_matches: Dict[str, bool],
) -> Set[str]:
    """Find variables whose values may be supplied by a section evaluation."""
    candidates = {
        f"${match.group(1)}"
        for match in re.finditer(
            rf'{section}\.\$([a-zA-Z0-9_]+)(?![a-zA-Z0-9_]*\*)',
            condition,
            flags=re.IGNORECASE,
        )
    }

    lower_condition = condition.lower()

    # Section wildcards and "N of section.*" need synthetic variables because the
    # helper receives match results, not the rule object or pattern count.
    max_wildcard_count = 0
    if f"{section}.*" in lower_condition:
        max_wildcard_count = 1

    n_of_pattern = rf'(\d+)\s+of\s+{section}(?:\.\*)?'
    for match in re.finditer(n_of_pattern, lower_condition):
        max_wildcard_count = max(max_wildcard_count, int(match.group(1)))

    named_section_quantifier = rf'\b(any|all)\s+of\s+{section}(?:\.\*)?\b'
    if re.search(named_section_quantifier, lower_condition):
        max_wildcard_count = max(max_wildcard_count, 1)

    section_prefix_quantifier = rf'(\d+)\s+of\s+{section}\.\$([a-zA-Z0-9_]+)\*'
    for match in re.finditer(section_prefix_quantifier, lower_condition):
        max_wildcard_count = max(max_wildcard_count, int(match.group(1)))

    for index in range(max_wildcard_count):
        candidates.add(f"$_{section}_wildcard_{index}")

    # Prefix quantifiers can be section-scoped or section-agnostic, so any
    # later section could satisfy them.
    for pattern in (
        rf'(any|all|\d+)\s+of\s+{section}\.\$([a-zA-Z0-9_]+)\*',
        r'(any|all|\d+)\s+of\s+\(\$([a-zA-Z0-9_]+)\*\)',
    ):
        for match in re.finditer(pattern, condition, flags=re.IGNORECASE):
            quantifier = match.group(1).lower()
            prefix = match.group(2)
            candidate_count = int(quantifier) if quantifier.isdigit() else 1
            for index in range(candidate_count):
                candidates.add(f"${prefix}_candidate_{index}")

    # Standalone variables are resolved in keyword -> semantic -> llm order by
    # evaluate_condition. A later section can only affect unresolved names.
    for variable in _standalone_variables(condition):
        if variable not in known_standalone_matches:
            candidates.add(variable)

    return candidates


def _section_can_change_condition(
    condition: str,
    keyword_matches: Dict[str, bool],
    semantic_matches: Dict[str, bool],
    llm_matches: Dict[str, bool],
    section: str,
    candidates: Set[str],
) -> bool:
    """Check whether candidate values for one section can alter the condition."""
    if not condition or not candidates:
        return False

    # Avoid exponential work for large wildcard-heavy conditions. In those cases,
    # evaluating the section is the safer behavior.
    if len(candidates) > 10:
        return True

    try:
        base_result = evaluate_condition(condition, keyword_matches, semantic_matches, llm_matches)
    except Exception:
        return True

    candidate_names = sorted(candidates)
    for values in product((False, True), repeat=len(candidate_names)):
        candidate_matches = dict(zip(candidate_names, values))
        test_keywords = keyword_matches
        test_semantics = semantic_matches
        test_llm = llm_matches

        if section == "keywords":
            test_keywords = {**keyword_matches, **candidate_matches}
        elif section == "semantics":
            test_semantics = {**semantic_matches, **candidate_matches}
        elif section == "llm":
            test_llm = {**llm_matches, **candidate_matches}

        try:
            if evaluate_condition(condition, test_keywords, test_semantics, test_llm) != base_result:
                return True
        except Exception:
            return True

    return False


def can_llm_change_outcome(condition: str, keyword_matches: Dict[str, bool],
                           semantic_matches: Dict[str, bool]) -> bool:
    """
    Determine if LLM evaluation could change the rule's match outcome.

    The function is conservative: if the condition references LLM values in a
    way that cannot be proven irrelevant, it returns True so correctness wins
    over skipping an API call.
    """
    known_matches = {**keyword_matches, **semantic_matches}
    candidates = _candidate_section_variables(condition, "llm", known_matches)
    return _section_can_change_condition(
        condition,
        keyword_matches,
        semantic_matches,
        {},
        "llm",
        candidates,
    )


def can_semantics_change_outcome(condition: str, keyword_matches: Dict[str, bool]) -> bool:
    """
    Determine if semantic evaluation could change the rule's match outcome.

    Standalone variables that were not resolved by keywords are treated as
    possible semantic values so conditions such as "$semantic_flag" still work.
    """
    candidates = _candidate_section_variables(condition, "semantics", keyword_matches)
    return _section_can_change_condition(
        condition,
        keyword_matches,
        {},
        {},
        "semantics",
        candidates,
    )


# Fix for the invalid regex handling in the parser
def validate_regex(pattern):
    """
    Validate that a regex pattern is valid.
    
    Args:
        pattern: The regex pattern to validate
        
    Returns:
        True if valid, False if invalid
    """
    try:
        re.compile(pattern)
        return True
    except re.error:
        return False


# Fix for None prompt handling in the matcher
def check_prompt_safe(prompt, matcher_obj):
    """
    Safely check a prompt against a rule, handling None and other edge cases.
    
    Args:
        prompt: The prompt to check
        matcher_obj: The matcher object (NovaMatcher instance)
        
    Returns:
        Match result dictionary
    """
    # Handle None prompt
    if prompt is None:
        return {
            "matched": False,
            "rule_name": matcher_obj.rule.name,
            "meta": matcher_obj.rule.meta,
            "matching_keywords": {},
            "matching_semantics": {},
            "matching_llm": {},
            "debug": {
                "condition": matcher_obj.rule.condition,
                "condition_result": False,
                "all_keyword_matches": {},
                "all_semantic_matches": {},
                "all_llm_matches": {}
            }
        }
    
    # Proceed with normal matching
    return matcher_obj.check_prompt(prompt)
