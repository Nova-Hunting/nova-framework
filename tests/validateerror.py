#!/usr/bin/env python3
"""
NOVA: Rule System Validator
Author: Claude
License: MIT License
Version: see nova._version
Description: A script to validate Nova rules and detect potential issues
"""

import os
import sys
import re
import json
import argparse
import traceback

# Add Nova module path if needed
# sys.path.append('/path/to/nova')

from nova.core.parser import NovaRuleFileParser
from nova.core.matcher import NovaMatcher
from nova.evaluators.condition import evaluate_condition

class NovaValidator:
    """
    Validator for Nova rules and ruleset.
    Detects issues, inconsistencies, and potential errors.
    """
    
    def __init__(self, rule_paths=None, test_prompts_path=None, verbose=False):
        """
        Initialize the validator.
        
        Args:
            rule_paths: List of paths to rule files or directories containing rules
            test_prompts_path: Path to a file containing test prompts
            verbose: Enable detailed output
        """
        self.rule_parser = NovaRuleFileParser()
        self.rule_paths = rule_paths or []
        self.test_prompts_path = test_prompts_path
        self.verbose = verbose
        self.rules = []
        self.test_prompts = []
        self.issues = []
        self.warnings = []
        
    def validate(self):
        """Run all validation checks."""
        print("Starting Nova Rule Validation...")
        print("=" * 70)
        
        # Parse rules
        self._load_rules()
        
        if not self.rules:
            print("No rules found. Please check your rule paths.")
            return False
            
        # Load test prompts if provided
        if self.test_prompts_path:
            self._load_test_prompts()
        
        # Validate rules
        self._validate_rules()
        
        # Test rules against prompts if available
        if self.test_prompts:
            self._test_rules_with_prompts()
        
        # Print summary
        self._print_summary()
        
        # Return whether validation was successful (no critical issues)
        return len(self.issues) == 0
    
    def _load_rules(self):
        """Load rules from files or directories."""
        print("\nLoading rules...")
        
        rules = []
        for path in self.rule_paths:
            if not os.path.exists(path):
                self.issues.append(f"Path does not exist: {path}")
                continue
                
            if os.path.isdir(path):
                # Load rules from directory
                for filename in os.listdir(path):
                    if filename.endswith('.nov') or filename.endswith('.nova'):
                        file_path = os.path.join(path, filename)
                        try:
                            file_rules = self.rule_parser.parse_file(file_path)
                            rules.extend(file_rules)
                            print(f"Loaded {len(file_rules)} rules from {file_path}")
                        except Exception as e:
                            self.issues.append(f"Error parsing rule file {file_path}: {str(e)}")
            else:
                # Load rules from file
                try:
                    file_rules = self.rule_parser.parse_file(path)
                    rules.extend(file_rules)
                    print(f"Loaded {len(file_rules)} rules from {path}")
                except Exception as e:
                    self.issues.append(f"Error parsing rule file {path}: {str(e)}")
        
        self.rules = rules
        print(f"Loaded {len(self.rules)} rules in total.")
    
    def _load_test_prompts(self):
        """Load test prompts from file."""
        print("\nLoading test prompts...")
        
        if not os.path.exists(self.test_prompts_path):
            self.issues.append(f"Test prompts file does not exist: {self.test_prompts_path}")
            return
            
        try:
            with open(self.test_prompts_path, 'r') as f:
                content = f.read()
                
            # Try parsing as JSON
            try:
                prompts = json.loads(content)
                if isinstance(prompts, list):
                    self.test_prompts = prompts
                elif isinstance(prompts, dict) and 'prompts' in prompts:
                    self.test_prompts = prompts['prompts']
                else:
                    self.issues.append(f"Invalid format in test prompts file: {self.test_prompts_path}")
                    return
            except json.JSONDecodeError:
                # Fall back to simple text format (one prompt per line)
                self.test_prompts = [line.strip() for line in content.split('\n') if line.strip()]
                
            print(f"Loaded {len(self.test_prompts)} test prompts.")
        except Exception as e:
            self.issues.append(f"Error loading test prompts: {str(e)}")
    
    def _validate_rules(self):
        """Validate individual rules."""
        print("\nValidating rules...")
        
        for rule in self.rules:
            print(f"Validating rule: {rule.name}")
            
            # Check if rule has meta information
            if not rule.meta:
                self.warnings.append(f"Rule '{rule.name}' has no meta information.")
            elif 'description' not in rule.meta:
                self.warnings.append(f"Rule '{rule.name}' has no description.")
                
            # Check if rule has at least one pattern
            if not rule.keywords and not rule.semantics and not rule.llms:
                self.issues.append(f"Rule '{rule.name}' has no patterns (keywords, semantics, or llm).")
                
            # Check patterns
            if rule.keywords:
                self._validate_patterns(rule, "keywords")
            
            if rule.semantics:
                self._validate_patterns(rule, "semantics")
                
            if rule.llms:
                self._validate_patterns(rule, "llms")
                
            # Check condition
            if not rule.condition:
                self.issues.append(f"Rule '{rule.name}' has no condition.")
            else:
                self._validate_condition(rule)
                
            # Check for unused variables
            self._check_unused_variables(rule)
            
            # Check for potentially redundant conditions
            self._check_redundant_conditions(rule)
    
    def _validate_patterns(self, rule, pattern_type):
        """Validate patterns of a specific type in a rule."""
        patterns = getattr(rule, pattern_type)
        
        for var_name, pattern in patterns.items():
            # Check variable name format
            if not var_name.startswith('$'):
                self.issues.append(f"Rule '{rule.name}': {pattern_type} variable '{var_name}' does not start with $.")
                
            # Check pattern based on type
            if pattern_type == "keywords":
                # Check for empty patterns
                if not pattern.pattern:
                    self.warnings.append(f"Rule '{rule.name}': Keyword '{var_name}' has empty pattern.")
                    
                # Check for very short patterns (potential false positives)
                elif len(pattern.pattern) < 3 and not pattern.is_regex:
                    self.warnings.append(f"Rule '{rule.name}': Keyword '{var_name}' has very short pattern '{pattern.pattern}' (potential false positives).")
                    
                # Check regex patterns
                if pattern.is_regex:
                    try:
                        re.compile(pattern.pattern)
                    except re.error as e:
                        self.issues.append(f"Rule '{rule.name}': Keyword '{var_name}' has invalid regex pattern: {str(e)}")
                        
            elif pattern_type == "semantics":
                # Check for empty patterns
                if not pattern.pattern:
                    self.warnings.append(f"Rule '{rule.name}': Semantic '{var_name}' has empty pattern.")
                    
                # Check threshold
                if pattern.threshold < 0 or pattern.threshold > 1:
                    self.issues.append(f"Rule '{rule.name}': Semantic '{var_name}' has invalid threshold {pattern.threshold} (must be between 0 and 1).")
                    
                # Check for very low thresholds
                elif pattern.threshold < 0.2:
                    self.warnings.append(f"Rule '{rule.name}': Semantic '{var_name}' has very low threshold {pattern.threshold} (potential false positives).")
                    
            elif pattern_type == "llms":
                # Check for empty patterns
                if not pattern.pattern:
                    self.warnings.append(f"Rule '{rule.name}': LLM '{var_name}' has empty pattern.")
                    
                # Check threshold
                if pattern.threshold < 0 or pattern.threshold > 1:
                    self.issues.append(f"Rule '{rule.name}': LLM '{var_name}' has invalid threshold {pattern.threshold} (must be between 0 and 1).")
                    
                # Check for very low thresholds
                elif pattern.threshold < 0.2:
                    self.warnings.append(f"Rule '{rule.name}': LLM '{var_name}' has very low threshold {pattern.threshold} (potential false positives).")
    
    def _validate_condition(self, rule):
        """Validate the condition of a rule."""
        condition = rule.condition
        
        # Check for balanced parentheses
        if condition.count('(') != condition.count(')'):
            self.issues.append(f"Rule '{rule.name}': Condition has unbalanced parentheses.")
            
        # Check for common syntax errors
        if ' of of ' in condition:
            self.issues.append(f"Rule '{rule.name}': Condition contains 'of of' (likely a typo).")
            
        if ' and and ' in condition:
            self.issues.append(f"Rule '{rule.name}': Condition contains 'and and' (likely a typo).")
            
        if ' or or ' in condition:
            self.issues.append(f"Rule '{rule.name}': Condition contains 'or or' (likely a typo).")
            
        # Check for undefined variables
        defined_vars = self._get_defined_variables(rule)
        undefined_vars = self._find_undefined_variables(rule, defined_vars)
        
        if undefined_vars:
            for var in undefined_vars:
                self.issues.append(f"Rule '{rule.name}': Condition references undefined variable: {var}")
                
        # Try to evaluate the condition with mock values
        try:
            # Create mock matches where all variables are True
            mock_keyword_matches = {var: True for var in rule.keywords}
            mock_semantic_matches = {var: True for var in rule.semantics}
            mock_llm_matches = {var: True for var in rule.llms}
            
            # Test evaluation
            evaluate_condition(condition, mock_keyword_matches, mock_semantic_matches, mock_llm_matches)
        except Exception as e:
            self.issues.append(f"Rule '{rule.name}': Error evaluating condition: {str(e)}")
            if self.verbose:
                traceback.print_exc()
    
    def _check_unused_variables(self, rule):
        """Check for unused variables in a rule."""
        defined_vars = self._get_defined_variables(rule)
        used_vars = self._find_used_variables(rule)
        
        unused_vars = defined_vars - used_vars
        if unused_vars:
            self.warnings.append(f"Rule '{rule.name}' has {len(unused_vars)} unused variables: {', '.join(sorted(unused_vars))}")
    
    def _check_redundant_conditions(self, rule):
        """Check for potentially redundant conditions."""
        condition = rule.condition
        
        # Check for patterns that might indicate redundant conditions
        if "any of keywords.* and any of keywords.*" in condition:
            self.warnings.append(f"Rule '{rule.name}': Condition contains 'any of keywords.* and any of keywords.*' which is redundant.")
            
        if "any of semantics.* and any of semantics.*" in condition:
            self.warnings.append(f"Rule '{rule.name}': Condition contains 'any of semantics.* and any of semantics.*' which is redundant.")
            
        if "any of llm.* and any of llm.*" in condition:
            self.warnings.append(f"Rule '{rule.name}': Condition contains 'any of llm.* and any of llm.*' which is redundant.")
    
    def _get_defined_variables(self, rule):
        """Get all variables defined in a rule."""
        defined_vars = set()
        
        # Add all defined variables
        for var in rule.keywords:
            defined_vars.add(var)
            
        for var in rule.semantics:
            defined_vars.add(var)
            
        for var in rule.llms:
            defined_vars.add(var)
            
        return defined_vars
    
    def _find_undefined_variables(self, rule, defined_vars):
        """Find variables used in condition but not defined in patterns."""
        condition = rule.condition
        undefined_vars = set()
        
        # Find directly referenced variables (excluding wildcards)
        # Pattern for section.$var (not section.$var*)
        section_vars = re.finditer(r'(keywords|semantics|llm)\.\$([a-zA-Z0-9_]+)(?!\*)', condition)
        for match in section_vars:
            section = match.group(1)
            var_name = "$" + match.group(2)
            
            # Check if variable exists in the appropriate section
            if section == "keywords" and var_name not in rule.keywords:
                undefined_vars.add(var_name)
            elif section == "semantics" and var_name not in rule.semantics:
                undefined_vars.add(var_name)
            elif section == "llm" and var_name not in rule.llms:
                undefined_vars.add(var_name)
                
        # Find standalone variables
        standalone_vars = re.finditer(r'(?<![a-zA-Z0-9_\.\$])(\$[a-zA-Z0-9_]+)(?!\*)', condition)
        for match in standalone_vars:
            var_name = match.group(1)
            
            # Check if variable exists in any section
            if var_name not in defined_vars:
                undefined_vars.add(var_name)
                
        return undefined_vars
    
    def _find_used_variables(self, rule):
        """Find variables used in the condition."""
        condition = rule.condition
        used_vars = set()
        
        # Section wildcards (e.g., keywords.*)
        if "keywords.*" in condition:
            used_vars.update(rule.keywords.keys())
            
        if "semantics.*" in condition:
            used_vars.update(rule.semantics.keys())
            
        if "llm.*" in condition:
            used_vars.update(rule.llms.keys())
            
        # Section prefix wildcards (e.g., keywords.$prefix*)
        prefix_wildcards = re.finditer(r'(keywords|semantics|llm)\.\$([a-zA-Z0-9_]+)\*', condition)
        for match in prefix_wildcards:
            section = match.group(1)
            prefix = match.group(2)
            
            # Mark variables with matching prefix as used
            if section == "keywords":
                for var in rule.keywords:
                    if var[1:].startswith(prefix):
                        used_vars.add(var)
            elif section == "semantics":
                for var in rule.semantics:
                    if var[1:].startswith(prefix):
                        used_vars.add(var)
            elif section == "llm":
                for var in rule.llms:
                    if var[1:].startswith(prefix):
                        used_vars.add(var)
                        
        # Any of wildcards (e.g., any of ($prefix*))
        any_of_wildcards = re.finditer(r'any\s+of\s+\(\$([a-zA-Z0-9_]+)\*\)', condition)
        for match in any_of_wildcards:
            prefix = match.group(1)
            
            # Mark variables with matching prefix in any section as used
            for section_vars in [rule.keywords, rule.semantics, rule.llms]:
                for var in section_vars:
                    if var[1:].startswith(prefix):
                        used_vars.add(var)
                        
        # Direct variable references
        section_vars = re.finditer(r'(keywords|semantics|llm)\.\$([a-zA-Z0-9_]+)(?!\*)', condition)
        for match in section_vars:
            var_name = "$" + match.group(2)
            used_vars.add(var_name)
            
        standalone_vars = re.finditer(r'(?<![a-zA-Z0-9_\.\$])(\$[a-zA-Z0-9_]+)(?!\*)', condition)
        for match in standalone_vars:
            var_name = match.group(1)
            used_vars.add(var_name)
            
        return used_vars
    
    def _test_rules_with_prompts(self):
        """Test rules against test prompts."""
        print("\nTesting rules with prompts...")
        
        # Create a matcher for each rule
        matchers = [NovaMatcher(rule) for rule in self.rules]
        
        # Test each prompt against each rule
        for i, prompt in enumerate(self.test_prompts):
            print(f"\nTesting prompt {i+1}/{len(self.test_prompts)}:")
            print(f"Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}")
            
            matching_rules = []
            
            for matcher in matchers:
                rule = matcher.rule
                try:
                    result = matcher.check_prompt(prompt)
                    if result['matched']:
                        matching_rules.append(rule.name)
                        
                        if self.verbose:
                            print(f"  Matched rule: {rule.name}")
                            print(f"  Matching keywords: {result['matching_keywords']}")
                            print(f"  Matching semantics: {result['matching_semantics']}")
                            print(f"  Matching LLM: {result['matching_llm']}")
                except Exception as e:
                    self.issues.append(f"Error matching prompt against rule '{rule.name}': {str(e)}")
                    if self.verbose:
                        traceback.print_exc()
            
            print(f"Matched {len(matching_rules)} rules: {', '.join(matching_rules) if matching_rules else 'None'}")
    
    def _print_summary(self):
        """Print validation summary."""
        print("\n" + "=" * 70)
        print("Validation Summary:")
        print(f"Total rules: {len(self.rules)}")
        print(f"Total test prompts: {len(self.test_prompts)}")
        print(f"Issues found: {len(self.issues)}")
        print(f"Warnings: {len(self.warnings)}")
        
        if self.issues:
            print("\nIssues:")
            for i, issue in enumerate(self.issues):
                print(f"{i+1}. {issue}")
                
        if self.warnings:
            print("\nWarnings:")
            for i, warning in enumerate(self.warnings):
                print(f"{i+1}. {warning}")
                
        print("\nValidation " + ("FAILED" if self.issues else "PASSED"))
    
    def export_report(self, output_path):
        """Export validation report to a file."""
        report = {
            "total_rules": len(self.rules),
            "total_test_prompts": len(self.test_prompts),
            "issues_count": len(self.issues),
            "warnings_count": len(self.warnings),
            "issues": self.issues,
            "warnings": self.warnings,
            "rules": [{"name": rule.name, "condition": rule.condition} for rule in self.rules],
            "validation_passed": len(self.issues) == 0
        }
        
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
            
        print(f"\nValidation report exported to {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate Nova rules and ruleset.")
    parser.add_argument("-r", "--rules", nargs="+", help="Paths to rule files or directories containing rules.")
    parser.add_argument("-p", "--prompts", help="Path to a file containing test prompts.")
    parser.add_argument("-o", "--output", help="Path to export validation report.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output.")
    
    args = parser.parse_args()
    
    validator = NovaValidator(rule_paths=args.rules, test_prompts_path=args.prompts, verbose=args.verbose)
    success = validator.validate()
    
    if args.output:
        validator.export_report(args.output)
    
    sys.exit(0 if success else 1)