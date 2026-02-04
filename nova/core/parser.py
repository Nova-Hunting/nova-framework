"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia
twitter: @fr0gger_
License: MIT License
Version: 1.0.0
Description: Temporary patched version of NovaParser that disables strict validation for wildcards
"""

import re
from typing import Dict, List, Optional, Set, Any
from nova.core.rules import NovaRule, KeywordPattern, SemanticPattern, LLMPattern
from nova.utils.logger import get_logger

# Get logger for this module
logger = get_logger("nova.parser")

# Precompile regex patterns for better performance
RULE_NAME_PATTERN = re.compile(r'rule\s+(\w+)(?:\s*{)?')
RULE_START_PATTERN = re.compile(r'rule\s+\w+\s*{?')
SECTION_WILDCARD_PATTERN = re.compile(r'(keywords|semantics|llm|fuzzy)\.\*')
VAR_PREFIX_PATTERN = re.compile(r'(keywords|semantics|llm|fuzzy)\.\$([a-zA-Z0-9_]+)\*')
ANY_OF_WILDCARD_PATTERN = re.compile(r'any\s+of\s+\(\$([a-zA-Z0-9_]+)\*\)')
DIRECT_VAR_PATTERN = re.compile(r'(keywords|semantics|llm|fuzzy)\.\$([a-zA-Z0-9_]+)')
STANDALONE_VAR_PATTERN = re.compile(r'(?<![a-zA-Z0-9_\.])(\$[a-zA-Z0-9_]+)')
NESTED_QUANTIFIERS_PATTERN = re.compile(r'\b(any|all|[0-9]+)\s+of\s+(any|all|[0-9]+)\s+of\b')
SECTION_REF_PATTERN = re.compile(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\.\$')
CONSECUTIVE_PARENS_PATTERN = re.compile(r'\)\s+\(')
QUANTIFIER_WITHOUT_OF_PATTERN = re.compile(r'\b(any|all)\b(?!\s+of\b)')

class NovaParserError(Exception):
    """Exception raised for Nova rule syntax errors."""
    pass


class NovaParser:
    """
    Parser for Nova rule files with grammar validation.
    Patched to handle wildcard patterns in conditions.
    """
    
    def __init__(self):
        """Initialize the parser."""
        self.current_section = None
        self.rule = None
        self.variable_names = {
            'keywords': set(),
            'semantics': set(),
            'llm': set()        
        }
    
    def parse(self, content: str) -> NovaRule:
        """
        Parse a Nova rule definition string into a NovaRule object.
        
        Args:
            content: The rule definition string
            
        Returns:
            A NovaRule object representing the parsed rule
            
        Raises:
            NovaParserError: If the rule definition doesn't follow the grammar
        """
        lines = content.strip().split('\n')
        
        # Reset variable tracking
        self.variable_names = {
            'keywords': set(),
            'semantics': set(),
            'llm': set()
        }
        
        # Check rule declaration and extract name
        rule_name = self._parse_rule_name(lines[0])
        self.rule = NovaRule(name=rule_name)
        
        current_section = None
        section_content = []
        
        # Parse rule content
        for line in lines[1:]:
            line = line.strip()
            if not line or line.startswith('//'):
                continue
                
            if line.endswith(':'):
                if current_section:
                    self._parse_section(current_section, section_content)
                current_section = line[:-1].strip()
                section_content = []
            elif line == '}':
                if current_section:
                    self._parse_section(current_section, section_content)
                break
            else:
                section_content.append(line)
        
        # Basic validation, with minimal variable checking
        self._validate_rule_structure()
        
        return self.rule
    
    def _parse_rule_name(self, line: str) -> str:
        """Extract the rule name from the rule declaration line."""
        match = RULE_NAME_PATTERN.match(line)
        if not match:
            raise NovaParserError(
                f"Invalid rule declaration: '{line}'. Must follow format 'rule RuleName' or 'rule RuleName {{'"
            )
        return match.group(1)
    
    def _parse_section(self, section: str, content: List[str]):
        """Parse a section of the rule definition."""
        section = section.lower()
        
        if section == "meta":
            self.rule.meta = self._parse_meta_section(content)
        elif section == "keywords":
            self.rule.keywords = self._parse_keywords_section(content)
        elif section == "semantics":
            self.rule.semantics = self._parse_semantics_section(content)
        elif section == "llm":
            self.rule.llms = self._parse_llm_section(content)
        elif section == "condition":
            self.rule.condition = self._parse_condition_section(content)
        else:
            # Unknown sections are ignored with a warning
            logger.warning(f"Unknown section '{section}' in rule '{self.rule.name}'")
    
    def _parse_meta_section(self, content: List[str]) -> Dict[str, str]:
        """Parse metadata from the meta section."""
        result = {}
        
        for line in content:
            line = line.strip()
            if not line or line.startswith('//'):
                continue
                
            if '=' not in line:
                continue
            
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip()
            
            # Extract value without quotes
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            
            result[key] = value
            
        return result

    
    def _parse_semantics_section(self, content: List[str]) -> Dict[str, SemanticPattern]:
        """Parse semantic patterns from the semantics section."""
        result = {}
        line_num = 0
        seen_variables = set()  # Track variables we've already seen
        
        for line in content:
            line_num += 1
            line = line.strip()
            if not line or line.startswith('//'):
                continue
            
            # Check for equals sign
            if '=' not in line:
                # Extract variable name for better error message
                parts = line.split()
                var_name = parts[0] if parts else "unknown"
                raise NovaParserError(
                    f"Missing equals sign at line {line_num}: '{line}'. Format should be '$variable = \"pattern\"'")
            
            key, value = line.split('=', 1)
            key = key.strip()
            
            # Check that variable name starts with $
            if not key.startswith('$'):
                raise NovaParserError(
                    f"Invalid semantics variable at line {line_num}: '{key}'. Variable names must start with $")
            
            # Check for duplicate variable names
            if key in seen_variables:
                raise NovaParserError(
                    f"Duplicate variable '{key}' at line {line_num}. Variable names must be unique within each section.")
            
            # Track that we've seen this variable
            seen_variables.add(key)
            
            # Track variable name for reference
            self.variable_names['semantics'].add(key)
            
            value = value.strip()
            
            # Check for pattern and optional threshold
            pattern_parts = value.split('(')
            pattern = pattern_parts[0].strip()
            
            # Extract pattern without quotes
            if pattern.startswith('"') and pattern.endswith('"'):
                pattern = pattern[1:-1]
            else:
                # Check if pattern is missing quotes
                raise NovaParserError(
                    f"Invalid semantics pattern at line {line_num}: '{pattern}'. Patterns must be in double quotes")
            
            # Parse threshold if provided
            threshold = 0.1  # Default threshold
            if len(pattern_parts) > 1:
                threshold_part = pattern_parts[1].strip()
                try:
                    threshold = float(threshold_part.rstrip(') '))
                    if not 0 <= threshold <= 1:
                        raise ValueError("Threshold must be between 0.0 and 1.0")
                except ValueError as e:
                    raise NovaParserError(
                        f"Invalid semantics threshold at line {line_num}: '{threshold_part}'. {str(e)}")
            
            result[key] = SemanticPattern(pattern=pattern, threshold=threshold)
            
        return result

    def _parse_llm_section(self, content: List[str]) -> Dict[str, LLMPattern]:
        """Parse LLM patterns from the llm section."""
        result = {}
        line_num = 0
        seen_variables = set()  # Track variables we've already seen
        
        for line in content:
            line_num += 1
            line = line.strip()
            if not line or line.startswith('//'):
                continue
            
            # Check for equals sign
            if '=' not in line:
                # Extract variable name for better error message
                parts = line.split()
                var_name = parts[0] if parts else "unknown"
                raise NovaParserError(
                    f"Missing equals sign at line {line_num}: '{line}'. Format should be '$variable = \"pattern\"'")
            
            key, value = line.split('=', 1)
            key = key.strip()
            
            # Check that variable name starts with $
            if not key.startswith('$'):
                raise NovaParserError(
                    f"Invalid LLM variable at line {line_num}: '{key}'. Variable names must start with $")
            
            # Check for duplicate variable names
            if key in seen_variables:
                raise NovaParserError(
                    f"Duplicate variable '{key}' at line {line_num}. Variable names must be unique within each section.")
            
            # Track that we've seen this variable
            seen_variables.add(key)
            
            # Track variable name for reference
            self.variable_names['llm'].add(key)
            
            value = value.strip()
            
            # Check for pattern and optional threshold
            pattern_parts = value.split('(')
            pattern = pattern_parts[0].strip()
            
            # Extract pattern without quotes
            if pattern.startswith('"') and pattern.endswith('"'):
                pattern = pattern[1:-1]
            else:
                # Check if pattern is missing quotes
                raise NovaParserError(
                    f"Invalid LLM prompt at line {line_num}: '{pattern}'. Prompts must be in double quotes")
            
            # Parse threshold if provided
            threshold = 0.6  # Default threshold
            if len(pattern_parts) > 1:
                threshold_part = pattern_parts[1].strip()
                try:
                    threshold = float(threshold_part.rstrip(') '))
                    if not 0 <= threshold <= 1:
                        raise ValueError("Threshold must be between 0.0 and 1.0")
                except ValueError as e:
                    raise NovaParserError(
                        f"Invalid LLM threshold at line {line_num}: '{threshold_part}'. {str(e)}")
            
            result[key] = LLMPattern(pattern=pattern, threshold=threshold)
            
        return result
    
    def _parse_keywords_section(self, content: List[str]) -> Dict[str, KeywordPattern]:
        """Parse keyword patterns from the keywords section."""
        result = {}
        seen_variables = set()
        
        for line_num, line in enumerate(content):
            if not line or line.strip().startswith('#'):
                continue
            
            try:
                key, value = map(str.strip, line.split('=', 1))
            except ValueError:
                raise NovaParserError(f"Invalid keyword pattern at line {line_num}: '{line}'")
            
            if not key.startswith('$'):
                raise NovaParserError(f"Invalid variable name '{key}' at line {line_num}")
            
            seen_variables.add(key)
            self.variable_names['keywords'].add(key)
            
            value = value.strip()

            # --- ADD THESE INITIALIZATIONS HERE ---
            is_fuzzy = False
            threshold = 80
            case_sensitive = False
            # --------------------------------------

            # 1. Check for Fuzzy Marker at the end of the line
            # Matches: "pattern" (85) fuzzy OR "pattern" fuzzy
            fuzzy_match = re.search(r'\((?P<threshold>\d+)\)\s+fuzzy$|(?P<marker>fuzzy)$', value, re.IGNORECASE)
            if fuzzy_match:
                is_fuzzy = True
                if fuzzy_match.group('threshold'):
                    threshold = int(fuzzy_match.group('threshold'))
                
                # Remove the fuzzy part from the value string so it doesn't break regex/string logic
                value = re.sub(r'\s*\(\d+\)\s+fuzzy$|\s+fuzzy$', '', value, flags=re.IGNORECASE).strip()

            # 2. Identify if it is a Regex
            is_regex = value.startswith('/') and value.rstrip('i').endswith('/')
            
            if is_regex:
                if value.endswith('i'):
                    value = value[1:-2]
                else:
                    value = value[1:-1]
                
                if "case:true" in value:
                    value = value.replace("case:true", "").strip()
                    case_sensitive = True
                
                try:
                    re.compile(value)
                except re.error as e:
                    raise NovaParserError(f"Invalid regex: {e}")
            else:
                # 3. Handle standard quoted strings
                if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                
                if "case:true" in value:
                    value = value.replace("case:true", "").strip()
                    case_sensitive = True
            
            # Now all variables (is_fuzzy, threshold, etc.) are defined!
            result[key] = KeywordPattern(
                pattern=value, 
                is_regex=is_regex, 
                case_sensitive=case_sensitive,
                is_fuzzy=is_fuzzy, 
                threshold=threshold
            )
            
        return result

    def _parse_condition_section(self, content: List[str]) -> str:
        """
        Parse the condition section with comprehensive syntax validation.
        
        Args:
            content: Lines in the condition section
            
        Returns:
            Condition expression as a string
            
        Raises:
            NovaParserError: If the condition syntax is invalid
        """
        
        # Join lines and clean up comments
        raw_condition = ' '.join(line.strip() for line in content 
                    if line.strip() and not line.strip().startswith('//'))

        if not raw_condition:
            raise NovaParserError("Condition section cannot be empty")
        
        # Normalize whitespace to avoid indent issues
        condition = re.sub(r'\s+', ' ', raw_condition).strip()
        
        # Check for improper nesting of quantifiers (e.g., "all of any of")
        nested_quantifiers = NESTED_QUANTIFIERS_PATTERN.finditer(condition)
        for match in nested_quantifiers:
            pos = match.start()
            context = condition[max(0, pos-20):min(len(condition), pos+20)]
            raise NovaParserError(
                f"Invalid nested quantifiers at position {pos}: '{match.group(0)}'. Quantifiers cannot be nested. Context: '...{context}...'")
        
        # Validate section references - check for misspelled section names
        valid_sections = ['keywords', 'semantics', 'llm' , 'fuzzy']
        
        # Find all potential section references that aren't in our valid list
        for match in SECTION_REF_PATTERN.finditer(condition):
            section = match.group(1).lower()
            if section not in valid_sections:
                pos = match.start(1)
                context = condition[max(0, pos-20):min(len(condition), pos+20)]
                # Try to suggest the correct section
                suggestions = []
                for valid in valid_sections:
                    # Simple similarity check
                    if valid[0] == section[0] or len(set(valid) & set(section)) > len(valid) / 2:
                        suggestions.append(valid)
                
                if suggestions:
                    suggestion_text = f" Did you mean {' or '.join(suggestions)}?"
                else:
                    suggestion_text = ""
                    
                raise NovaParserError(
                    f"Invalid section name '{section}' at position {pos}.{suggestion_text} Valid sections are: {', '.join(valid_sections)}\nContext: '...{context}...'")
        
        # Check for balanced parentheses
        open_count = condition.count('(')
        close_count = condition.count(')')
        
        if open_count > close_count:
            raise NovaParserError(
                f"Unbalanced parentheses in condition: missing {open_count - close_count} closing parenthesis ')'")
        elif close_count > open_count:
            raise NovaParserError(
                f"Unbalanced parentheses in condition: extra {close_count - open_count} closing parenthesis ')'")
        
        # More advanced validation for nested parentheses
        stack = []
        for i, char in enumerate(condition):
            if char == '(':
                stack.append(i)
            elif char == ')':
                if not stack:
                    # Found closing parenthesis without matching opening
                    context = condition[max(0, i-20):min(len(condition), i+20)]
                    raise NovaParserError(
                        f"Mismatched closing parenthesis at position {i}: '...{context}...'")
                stack.pop()
        
        if stack:
            # Some opening parentheses were never closed
            pos = stack[0]
            context = condition[max(0, pos-20):min(len(condition), pos+20)]
            raise NovaParserError(
                f"Unclosed parenthesis at position {pos}: '...{context}...'")
        
        # Check that 'any' and 'all' are always followed by 'of'
        quantifier_matches = list(QUANTIFIER_WITHOUT_OF_PATTERN.finditer(condition))
        for match in quantifier_matches:
            pos = match.start()
            quantifier = match.group(1)
            context = condition[max(0, pos-20):min(len(condition), pos+20)]
            raise NovaParserError(
                f"Invalid usage of '{quantifier}' at position {pos}. '{quantifier}' should be followed by 'of': '...{context}...'")
        
        # Check for 'of' usage - it should always be preceded by 'any', 'all', or a number
        of_instances = [m.start() for m in re.finditer(r'\bof\b', condition)]
        for pos in of_instances:
            # Look at what comes before 'of'
            before_of = condition[:pos].strip()
            # Check if it ends with 'any', 'all', or a number
            if not re.search(r'\b(any|all|\d+)\s*$', before_of):
                context = condition[max(0, pos-20):min(len(condition), pos+20)]
                raise NovaParserError(
                    f"Invalid usage of 'of' at position {pos}. 'of' should be preceded by 'any', 'all', or a number: '...{context}...'")
        
        # Check for consecutive expressions without logical operators
        # First remove strings in quotes to avoid false positives
        cleaned_condition = re.sub(r'"[^"]*"', '"string"', condition)

        
        # Check for consecutive closing/opening parenthesis patterns without operators
        pattern = r'\)\s+\('
        matches = CONSECUTIVE_PARENS_PATTERN.finditer(cleaned_condition)
        for match in matches:
            pos = match.start()
            context = condition[max(0, pos-20):min(len(condition), pos+20)]
            raise NovaParserError(
                f"Missing logical operator (and/or) at position {pos}: '...{context}...'")
        
        # Check for consecutive expression patterns that might indicate missing operators
        # Look for "any of" followed by another "any of" without logical operator
        pattern = r'any\s+of\s+\([^)]+\)\s+(?!and\s|or\s|not\s)(any\s+of|\$)'
        matches = re.finditer(pattern, cleaned_condition, re.IGNORECASE)
        for match in matches:
            pos = match.start(1)  # Position of the second expression
            context = condition[max(0, pos-20):min(len(condition), pos+20)]
            raise NovaParserError(
                f"Missing logical operator (and/or) before expression at position {pos}: '...{context}...'")
        
        # Check for other consecutive expressions without operators
        # This is a simplified check and might have false positives
        pattern = r'\)\s+(?!and\s|or\s|not\s|\)|\Z)(\w)'
        matches = re.finditer(pattern, cleaned_condition)
        for match in matches:
            pos = match.start(1)
            context = condition[max(0, pos-20):min(len(condition), pos+20)]
            raise NovaParserError(
                f"Possible missing logical operator (and/or) at position {pos}: '...{context}...'")
        
        # Check for keyword operators (and, or, not)
        if ' and ' not in condition.lower() and ' or ' not in condition.lower() and 'not ' not in condition.lower():
            if '(' in condition and ')' in condition:
                # Might be using parentheses without logical operators
                pass
            #else:
            #    print("[!] Warning: Rule has condition that doesn't contain any logical operators (and, or, not)")
        
        return condition
    
    def _validate_rule_structure(self):
        """
        Validate the overall rule structure and check for undefined variables.
        
        Raises:
            NovaParserError: If the rule structure is invalid
        """
        try:
            # Check that at least one pattern type is specified
            if not self.rule.keywords and not self.rule.semantics and not self.rule.llms:
                raise NovaParserError(
                    f"Rule '{self.rule.name}' must specify at least one of: keywords, semantics, llm")
            
            # Check that condition is specified
            if not self.rule.condition:
                raise NovaParserError(
                    f"Rule '{self.rule.name}' must have a condition section")
            
            # Check for misplaced variables (wrong section)
            for section, vars_dict in [
                ('semantics', self.rule.semantics),
                ('keywords', self.rule.keywords),
                ('llm', self.rule.llms)
            ]:
                for var_name in vars_dict.keys():
                    if not var_name.startswith('$'):
                        raise NovaParserError(
                            f"Rule '{self.rule.name}': Variable '{var_name}' in {section} section must start with $")
                    
                    # Check if the variable name contains another section prefix
                    for other_section in ['keywords', 'semantics', 'llm']:
                        if other_section != section and var_name.startswith('$' + other_section):
                            raise NovaParserError(
                                f"Rule '{self.rule.name}': Variable '{var_name}' in {section} section appears to belong to {other_section} section")
            
            # IMPORTANT: Always validate variable references in condition, even with wildcards
            try:
                self._validate_condition_variables()
            except NovaParserError as e:
                # Add rule name to the error if not already there
                error_message = str(e)
                if not error_message.startswith(f"Rule '{self.rule.name}'"):
                    raise NovaParserError(f"Rule '{self.rule.name}': {error_message}")
                raise
            
            # Check for basic condition syntax errors
            try:
                # Normalize condition whitespace completely before validation
                # This is critical to avoid whitespace/indentation errors
                normalized_condition = re.sub(r'\s+', ' ', self.rule.condition).strip()
                
                # Check if the original condition had multiple lines
                condition_lines = self.rule.condition.split('\n')
                if len(condition_lines) > 1:
                    # Only check for inconsistent indentation if we're not normalizing
                    leading_spaces = [len(line) - len(line.lstrip()) for line in condition_lines if line.strip()]
                    if len(set(leading_spaces)) > 1:
                        print(f"[!] Warning: Rule '{self.rule.name}': Inconsistent indentation detected in condition. Normalizing whitespace.")
                        
                # Use the normalized condition for all validation
                cleaned_condition = normalized_condition
                
                # Check for syntax patterns
                if re.search(r'\bof\s+\([^)]*\)', cleaned_condition):
                    raise NovaParserError(f"Rule '{self.rule.name}': Invalid syntax: 'of (keywords.$var*)'. Use section prefix in the variable reference instead (e.g., 'of keywords.$var*')")
                
                # Check for incorrect parentheses in wildcards - make sure to only match problematic patterns
                if re.search(r'\(\s*(keywords|semantics|llm)\.\*\s*\)', cleaned_condition):
                    raise NovaParserError(f"Rule '{self.rule.name}': Invalid wildcard syntax: section wildcards should not be enclosed in parentheses. Use 'keywords.*' instead of '(keywords.*)'")
                                
                # For compile check, we need to process the condition differently
                syntax_check_condition = cleaned_condition
                
                # Replace section wildcards first since they're easier to detect
                section_wildcards = ["keywords.*", "semantics.*", "llm.*"]
                for wildcard in section_wildcards:
                    syntax_check_condition = syntax_check_condition.replace(wildcard, "True")
                
                # Replace "any of section.*" patterns - these cause syntax errors
                syntax_check_condition = re.sub(r'any\s+of\s+(keywords|semantics|llm)\.\*', 'True', syntax_check_condition)
                
                # Replace variable references with True
                syntax_check_condition = re.sub(r'[a-zA-Z0-9_]+\.\$[a-zA-Z0-9_]+\*?', 'True', syntax_check_condition)
                syntax_check_condition = re.sub(r'\$[a-zA-Z0-9_]+\*?', 'True', syntax_check_condition)
                
                # Replace "any of" and similar constructs
                syntax_check_condition = re.sub(r'(?:any|all|\d+)\s+of\s+\([^)]+\)', 'True', syntax_check_condition)
                
                # Normalize logical operators
                syntax_check_condition = re.sub(r'\b(and|or|not)\b', lambda m: m.group(0).lower(), syntax_check_condition)
                
                # Normalize again before adding spaces around parentheses
                syntax_check_condition = re.sub(r'\s+', ' ', syntax_check_condition).strip()
                
                # Add spaces around parentheses in a way that doesn't create extra spaces
                syntax_check_condition = syntax_check_condition.replace('(', ' ( ').replace(')', ' ) ')
                
                # Final normalization to clean up any double spaces created
                syntax_check_condition = re.sub(r'\s+', ' ', syntax_check_condition).strip()
                
                # Skip the compile check if the condition has Nova-specific syntax
                has_nova_specific_syntax = False
                if re.search(r'any\s+of\s+', cleaned_condition) or re.search(r'all\s+of\s+', cleaned_condition) or '.*' in cleaned_condition:
                    has_nova_specific_syntax = True
                
                # Only do the compile check if there's no Nova-specific syntax
                if not has_nova_specific_syntax:
                    try:
                        compile(syntax_check_condition, '<string>', 'eval')
                    except SyntaxError as e:
                        # Provide more detailed error message
                        line_info = f" at line {e.lineno}, column {e.offset}" if hasattr(e, 'lineno') and hasattr(e, 'offset') else ""
                        context = e.text.strip() if hasattr(e, 'text') and e.text else ""
                        
                        error_message = f"Rule '{self.rule.name}': Invalid condition syntax: {e.msg}{line_info}"
                        if context:
                            error_message += f"\nContext: '{context}'"
                            
                        # Suggest fixes based on common issues
                        if "unexpected indent" in e.msg:
                            error_message += "\nCheck for extra spaces or line breaks in your condition. Make sure multi-line conditions are properly aligned and don't have inconsistent indentation."
                        elif "unexpected EOF" in e.msg:
                            error_message += "\nThe condition expression is incomplete. Check for missing closing parentheses or operators."
                        elif "invalid syntax" in e.msg:
                            error_message += "\nThis could be caused by incorrect operators, missing parentheses, or incorrect variable references. Make sure to use 'and', 'or', 'not' for operators and proper 'section.$variable' syntax."
                        
                        raise NovaParserError(error_message)
                        
            except NovaParserError:
                # Re-raise NovaParserError without modification
                raise
            except Exception as e:
                # Convert other exceptions to a more helpful error message
                error_type = type(e).__name__
                error_message = f"Rule '{self.rule.name}': Error validating condition: {str(e)} ({error_type})"
                
                # Add hints for common errors
                if "parentheses" in str(e).lower() or "bracket" in str(e).lower():
                    error_message += "\nCheck that your parentheses are balanced and properly nested."
                elif "operator" in str(e).lower():
                    error_message += "\nCheck that you're using valid operators (and, or, not) with proper spacing."
                
                raise NovaParserError(error_message)
            
            # Always check for unused variables, regardless of wildcards
            self._check_unused_variables()
            
        except NovaParserError:
            # Re-raise NovaParserError without modification (we've already added rule name)
            raise
        except Exception as e:
            # For any other unexpected errors, add the rule name
            raise NovaParserError(f"Rule '{self.rule.name}': Unexpected error: {str(e)}")

    def _check_unused_variables(self):
        """
        Check for variables defined in pattern sections but not used in the condition.
        Updated to handle fuzzy-to-keyword mapping.
        """
        # Get all defined variables
        all_variables = set()
        for section, vars_set in self.variable_names.items():
            all_variables.update(vars_set)
        
        # Find variables used in the condition
        used_variables = set()
        condition = self.rule.condition
        
        # 1. Check for section wildcards (e.g., keywords.*, fuzzy.*)
        section_wildcards = ['keywords', 'semantics', 'llm', 'fuzzy']
        
        for section in section_wildcards:
            if f"{section}.*" in condition or f"any of {section}.*" in condition:
                if section == 'fuzzy':
                    # 'fuzzy.*' uses all keywords marked as fuzzy
                    for var_name, pattern in self.rule.keywords.items():
                        if getattr(pattern, 'is_fuzzy', False):
                            used_variables.add(var_name)
                elif section in self.variable_names:
                    used_variables.update(self.variable_names[section])
        
        # 2. Check for prefix wildcards (e.g., keywords.$bypass*)
        for section in ['keywords', 'semantics', 'llm', 'fuzzy']:
            pattern = rf'{section}\.\$([a-zA-Z0-9_]+)\*'
            for match in re.finditer(pattern, condition):
                prefix = match.group(1)
                # Map fuzzy prefix to keywords section
                target_section = 'keywords' if section == 'fuzzy' else section
                if target_section in self.variable_names:
                    for var in self.variable_names[target_section]:
                        if var[1:].startswith(prefix):
                            used_variables.add(var)
        
        # 3. Check for direct variable references (e.g., fuzzy.$admin)
        # We add 'fuzzy' to the capture group here
        var_pattern = r'(keywords|semantics|llm|fuzzy)\.\$([a-zA-Z0-9_]+)(?!\*)'
        for match in re.finditer(var_pattern, condition):
            var_name = f"${match.group(2)}"
            used_variables.add(var_name)
        
        # 4. Check for standalone variables ($var)
        standalone_pattern = r'(?<![a-zA-Z0-9_\.])(\$[a-zA-Z0-9_]+)(?!\*)'
        for match in re.finditer(standalone_pattern, condition):
            used_variables.add(match.group(1))
        
        # Find unused variables
        unused_variables = all_variables - used_variables
        if unused_variables:
            unused_list = ", ".join(sorted(unused_variables))
            print(f"[!] Warning: Rule '{self.rule.name}' has {len(unused_variables)} unused variables: {unused_list}")

    def _validate_direct_variables(self):
        """Validate only direct variable references, skipping wildcards."""
        condition = self.rule.condition
        
        # Simple check for explicitly referenced variables (only for non-wildcard vars)
        # Patterns like 'semantics.$var' and 'llm.$var'
        for section in ['semantics', 'llm']:
            pattern = rf'{section}\.\$(\w+)'
            for match in re.finditer(pattern, condition):
                var_name = f"${match.group(1)}"
                if var_name not in self.variable_names[section]:
                    raise NovaParserError(
                        f"Condition references undefined {section} variable: {var_name}")
    
    def _validate_condition_variables(self):
        """
        Validate variable references in the condition.
        Updated to allow 'fuzzy' as a valid section mapping to 'keywords'.
        """
        condition = self.rule.condition
        working_condition = condition
        
        # 1. Check section.* patterns (e.g., keywords.*, fuzzy.*)
        for match in SECTION_WILDCARD_PATTERN.finditer(working_condition):
            section = match.group(1)
            working_condition = working_condition.replace(f"{section}.*", "TRUE")
        
        # 2. Check section.$prefix* patterns (e.g., fuzzy.$injection*)
        for match in VAR_PREFIX_PATTERN.finditer(condition):
            section = match.group(1)
            prefix = match.group(2)
            full_match = match.group(0)
            
            # Map fuzzy to keywords
            check_section = 'keywords' if section == 'fuzzy' else section
            
            has_match = False
            for var in self.variable_names.get(check_section, set()):
                if var[1:].startswith(prefix):
                    has_match = True
                    break
            
            if not has_match:
                raise NovaParserError(
                    f"Wildcard '{full_match}' in condition doesn't match any defined variables")
            
            working_condition = working_condition.replace(full_match, "TRUE")
        
        # 3. Handle "any of" wildcards (Logic remains same, fuzzy is handled in loop)
        for match in ANY_OF_WILDCARD_PATTERN.finditer(condition):
            prefix = match.group(1)
            full_match = match.group(0)
            has_match = False
            for section_vars in self.variable_names.values():
                for var in section_vars:
                    if var[1:].startswith(prefix):
                        has_match = True
                        break
                if has_match: break
            if not has_match:
                raise NovaParserError(f"Wildcard '{full_match}' in condition doesn't match any defined variables")
            working_condition = working_condition.replace(full_match, "TRUE")
        
        # 4. Check section.$var patterns (e.g., fuzzy.$admin)
        for match in DIRECT_VAR_PATTERN.finditer(working_condition):
            section = match.group(1)
            var_name = f"${match.group(2)}"
            
            # --- FIX START ---
            # Allow 'fuzzy' section name
            if section not in self.variable_names and section != 'fuzzy':
                raise NovaParserError(f"Invalid section '{section}' in condition")
            
            # Map fuzzy lookup to keywords variable names
            check_section = 'keywords' if section == 'fuzzy' else section
            
            if var_name not in self.variable_names.get(check_section, set()):
                raise NovaParserError(
                    f"Condition references undefined variable '{var_name}' in {section} section")
            # --- FIX END ---
            
        # 5. Check standalone variables ($var)
        for match in STANDALONE_VAR_PATTERN.finditer(working_condition):
            var_name = match.group(1)
            found = False
            for section_vars in self.variable_names.values():
                if var_name in section_vars:
                    found = True
                    break
            if not found:
                raise NovaParserError(f"Condition references undefined variable '{var_name}'")


class NovaRuleFileParser:
    """
    Parser for files containing multiple Nova rules.
    Enforces unique rule names within a file.
    """
    
    def __init__(self):
        """Initialize the rule file parser."""
        self.rule_parser = NovaParser()
        
    def parse_file(self, file_path: str) -> List[NovaRule]:
        """
        Parse a file containing multiple Nova rules.
        
        Args:
            file_path: Path to the rule file
            
        Returns:
            List of NovaRule objects
            
        Raises:
            FileNotFoundError: If the file doesn't exist
            NovaParserError: If there are syntax or validation errors
        """
        try:
            # Use context manager for efficient file handling
            with open(file_path, 'r') as f:
                content = f.read()
                return self.parse_content(content, file_path)
        except FileNotFoundError:
            raise FileNotFoundError(f"Rule file not found: {file_path}")
        except Exception as e:
            if isinstance(e, NovaParserError):
                raise
            raise NovaParserError(f"Error reading rule file {file_path}: {str(e)}")
    
    def parse_content(self, content: str, source_name: str = "input") -> List[NovaRule]:
        """
        Parse content containing multiple Nova rules.
        
        Args:
            content: String containing multiple rule definitions
            source_name: Name of the source for error messages
            
        Returns:
            List of NovaRule objects
            
        Raises:
            NovaParserError: If there are syntax or validation errors
        """
        # Extract individual rule blocks using the optimized method
        rule_blocks = self._extract_rule_blocks_optimized(content)
        
        if not rule_blocks:
            raise NovaParserError(f"No valid rules found in {source_name}")
        
        # Parse each rule block
        rules = []
        rule_names: Set[str] = set()
        
        for i, rule_block in enumerate(rule_blocks):
            try:
                rule = self.rule_parser.parse(rule_block)
                
                # Check for duplicate rule names
                if rule.name in rule_names:
                    raise NovaParserError(f"Duplicate rule name '{rule.name}' in {source_name}")
                
                rule_names.add(rule.name)
                rules.append(rule)
                
            except NovaParserError as e:
                # Add context to the error
                raise NovaParserError(f"Error in rule #{i+1} in {source_name}: {str(e)}")
        
        return rules
    
    def _extract_rule_blocks_optimized(self, content: str) -> List[str]:
        """
        Extract individual rule blocks from content using a more efficient approach.
        This method is optimized for speed over the original implementation.
        
        Args:
            content: String containing multiple rule definitions
            
        Returns:
            List of strings, each containing a single rule
        """
        # Find all potential rule declarations using our precompiled pattern
        rule_matches = list(RULE_START_PATTERN.finditer(content))
        
        if not rule_matches:
            return []
        
        # Extract each rule block with a single pass
        rule_blocks = []
        
        # Process all rule declarations
        for i, match in enumerate(rule_matches):
            start_pos = match.start()
            
            # Find the end of this rule (either next rule start or EOF)
            if i < len(rule_matches) - 1:
                end_pos = rule_matches[i+1].start()
            else:
                end_pos = len(content)
            
            # Extract the rule text
            rule_text = content[start_pos:end_pos].strip()
            
            # Verify rule completeness (has balanced braces)
            # We use a faster, single-pass algorithm here
            brace_count = 0
            rule_end_pos = -1
            
            for pos, char in enumerate(rule_text):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        # Found complete rule
                        rule_end_pos = pos + 1
                        break
            
            if rule_end_pos > 0:
                # If we found a valid end, make sure we only include the complete rule
                rule_blocks.append(rule_text[:rule_end_pos].strip())
            else:
                # If braces aren't balanced, use the whole text up to next rule
                # This maintains backward compatibility with original behavior
                rule_blocks.append(rule_text)
        
        return rule_blocks