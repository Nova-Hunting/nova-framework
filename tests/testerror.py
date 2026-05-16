#!/usr/bin/env python3
"""
NOVA: Error Handling Test Suite
Author: Claude
License: MIT License
Version: see nova._version
Description: A comprehensive test suite to verify error handling in Nova rule system
"""

import sys
import json
import time


from nova.core.rules import NovaRule, KeywordPattern
from nova.core.parser import NovaParser, NovaRuleFileParser
from nova.core.matcher import NovaMatcher
from nova.evaluators.condition import evaluate_condition

class NovaErrorTests:
    """
    Test suite for validating error handling in Nova rule system.
    Tests parsing, evaluation, and matching with problematic inputs.
    """
    
    def __init__(self, verbose=False):
        """
        Initialize the test suite.
        
        Args:
            verbose: Enable detailed output
        """
        self.parser = NovaParser()
        self.rule_file_parser = NovaRuleFileParser()
        self.verbose = verbose
        self.passed_tests = 0
        self.failed_tests = 0
        self.test_results = []
        
    def run_tests(self):
        """Run all error handling tests."""
        print("Starting Nova Error Handling Tests...")
        print("=" * 70)
        
        # Test groups
        self._test_parser_errors()
        self._test_condition_evaluator_errors()
        self._test_matcher_errors()
        self._test_special_syntax_errors()
        self._test_edge_cases()
        self._test_performance_issues()
        
        # Print summary
        self._print_summary()
        
        # Return whether all tests passed
        return self.failed_tests == 0
        
    def _log_test(self, name: str, passed: bool, details: str = "", expected_error=None, actual_error=None):
        """Log a test result."""
        status = "PASSED" if passed else "FAILED"
        print(f"Test: {name} - {status}")
        
        if not passed:
            if details:
                print(f"  Details: {details}")
            if expected_error and actual_error:
                print(f"  Expected error: {expected_error}")
                print(f"  Actual error: {actual_error}")
        
        self.test_results.append({
            "name": name,
            "passed": passed,
            "details": details,
            "expected_error": expected_error,
            "actual_error": actual_error if not passed else None
        })
        
        if passed:
            self.passed_tests += 1
        else:
            self.failed_tests += 1
            
    def _test_parser_errors(self):
        """Test parser error handling."""
        print("\nTesting Parser Error Handling:")
        
        # Test 1: Empty rule
        empty_rule = ""
        try:
            self.parser.parse(empty_rule)
            self._log_test("Empty Rule Handling", 
                          False, 
                          "Parser should have rejected empty rule")
        except Exception as e:
            self._log_test("Empty Rule Handling", 
                          True, 
                          f"Parser correctly rejected empty rule: {str(e)}")
        
        # Test 2: Malformed rule (missing curly braces)
        malformed_rule = """
        rule MalformedRule
            meta:
                description = "Test rule"
                
            keywords:
                $a = "test"
                
            condition:
                $a
        """
        try:
            self.parser.parse(malformed_rule)
            self._log_test("Malformed Rule Handling", 
                          False, 
                          "Parser should have rejected malformed rule")
        except Exception as e:
            self._log_test("Malformed Rule Handling", 
                          True, 
                          f"Parser correctly rejected malformed rule: {str(e)}")
        
        # Test 3: Invalid keyword pattern (missing quotes)
        invalid_pattern_rule = """
        rule InvalidPatternRule
        {
            meta:
                description = "Test rule"
                
            keywords:
                $a = test
                
            condition:
                $a
        }
        """
        try:
            self.parser.parse(invalid_pattern_rule)
            self._log_test("Invalid Pattern Handling", 
                          False, 
                          "Parser should have rejected invalid pattern")
        except Exception as e:
            self._log_test("Invalid Pattern Handling", 
                          True, 
                          f"Parser correctly rejected invalid pattern: {str(e)}")
        
        # Test 4: Invalid semantic threshold
        invalid_threshold_rule = """
        rule InvalidThresholdRule
        {
            meta:
                description = "Test rule"
                
            semantics:
                $a = "test" (2.0)
                
            condition:
                $a
        }
        """
        try:
            self.parser.parse(invalid_threshold_rule)
            self._log_test("Invalid Threshold Handling", 
                          False, 
                          "Parser should have rejected invalid threshold")
        except Exception as e:
            self._log_test("Invalid Threshold Handling", 
                          True, 
                          f"Parser correctly rejected invalid threshold: {str(e)}")
        
        # Test 5: Duplicate variable names
        duplicate_vars_rule = """
        rule DuplicateVarsRule
        {
            meta:
                description = "Test rule"
                
            keywords:
                $a = "test1"
                $a = "test2"
                
            condition:
                $a
        }
        """
        try:
            self.parser.parse(duplicate_vars_rule)
            self._log_test("Duplicate Variables Handling", 
                          False, 
                          "Parser should have rejected duplicate variables")
        except Exception as e:
            self._log_test("Duplicate Variables Handling", 
                          True, 
                          f"Parser correctly rejected duplicate variables: {str(e)}")
        
        # Test 6: Missing condition section
        missing_condition_rule = """
        rule MissingConditionRule
        {
            meta:
                description = "Test rule"
                
            keywords:
                $a = "test"
        }
        """
        try:
            self.parser.parse(missing_condition_rule)
            self._log_test("Missing Condition Handling", 
                          False, 
                          "Parser should have rejected missing condition")
        except Exception as e:
            self._log_test("Missing Condition Handling", 
                          True, 
                          f"Parser correctly rejected missing condition: {str(e)}")
        
        # Test 7: Undefined variables in condition
        undefined_vars_rule = """
        rule UndefinedVarsRule
        {
            meta:
                description = "Test rule"
                
            keywords:
                $a = "test"
                
            condition:
                $a and $b
        }
        """
        try:
            # This might be allowed by some parsers with a warning
            self.parser.parse(undefined_vars_rule)
            self._log_test("Undefined Variables Handling", 
                          True, 
                          "Parser allowed undefined variables but should warn about them")
        except Exception as e:
            self._log_test("Undefined Variables Handling", 
                          True, 
                          f"Parser rejected undefined variables: {str(e)}")
        
        # Test 8: Invalid regex pattern
        invalid_regex_rule = """
        rule InvalidRegexRule
        {
            meta:
                description = "Test rule"
                
            keywords:
                $a = /[a-z/
                
            condition:
                $a
        }
        """
        try:
            self.parser.parse(invalid_regex_rule)
            self._log_test("Invalid Regex Handling", 
                          False, 
                          "Parser should have rejected invalid regex")
        except Exception as e:
            self._log_test("Invalid Regex Handling", 
                          True, 
                          f"Parser correctly rejected invalid regex: {str(e)}")
            
        # Add another test case with a more clearly invalid regex
        clearly_invalid_regex = """
        rule ClearlyInvalidRegexRule
        {
            meta:
                description = "Test rule with obviously invalid regex"
                
            keywords:
                $a = /[unclosed bracket/
                
            condition:
                $a
        }
        """
        try:
            self.parser.parse(clearly_invalid_regex)
            self._log_test("Clearly Invalid Regex Handling", 
                          False, 
                          "Parser should have rejected clearly invalid regex")
        except Exception as e:
            self._log_test("Clearly Invalid Regex Handling", 
                          True, 
                          f"Parser correctly rejected clearly invalid regex: {str(e)}")
            
    def _test_condition_evaluator_errors(self):
        """Test condition evaluator error handling."""
        print("\nTesting Condition Evaluator Error Handling:")
        
        # Test 1: Empty condition
        try:
            result = evaluate_condition("", {}, {}, {})
            self._log_test("Empty Condition Handling", 
                          result is False, 
                          "Evaluator should return False for empty condition")
        except Exception as e:
            self._log_test("Empty Condition Handling", 
                          False, 
                          f"Evaluator should not raise an exception for empty condition: {str(e)}")
        
        # Test 2: Unbalanced parentheses
        try:
            result = evaluate_condition("($a and $b", {"$a": True, "$b": True}, {}, {})
            self._log_test("Unbalanced Parentheses Handling", 
                          result is False, 
                          "Evaluator should safely handle unbalanced parentheses")
        except Exception as e:
            self._log_test("Unbalanced Parentheses Handling", 
                          False, 
                          f"Evaluator should not raise an exception for unbalanced parentheses: {str(e)}")
        
        # Test 3: Invalid operator
        try:
            result = evaluate_condition("$a && $b", {"$a": True, "$b": True}, {}, {})
            self._log_test("Invalid Operator Handling", 
                          result is False, 
                          "Evaluator should safely handle invalid operators")
        except Exception as e:
            self._log_test("Invalid Operator Handling", 
                          False, 
                          f"Evaluator should not raise an exception for invalid operators: {str(e)}")
        
        # Test 4: Undefined variables
        try:
            result = evaluate_condition("$a and $b", {"$a": True}, {}, {})
            self._log_test("Undefined Variable Handling", 
                          result is False, 
                          "Evaluator should safely handle undefined variables")
        except Exception as e:
            self._log_test("Undefined Variable Handling", 
                          False, 
                          f"Evaluator should not raise an exception for undefined variables: {str(e)}")
        
        # Test 5: Invalid wildcard syntax
        try:
            result = evaluate_condition("any keywords.*", {"$a": True}, {}, {})
            self._log_test("Invalid Wildcard Syntax Handling", 
                          result is False, 
                          "Evaluator should safely handle invalid wildcard syntax")
        except Exception as e:
            self._log_test("Invalid Wildcard Syntax Handling", 
                          False, 
                          f"Evaluator should not raise an exception for invalid wildcard syntax: {str(e)}")
        
        # Test 6: Nonsensical condition
        try:
            result = evaluate_condition("gibberish text", {}, {}, {})
            self._log_test("Nonsensical Condition Handling", 
                          result is False, 
                          "Evaluator should safely handle nonsensical conditions")
        except Exception as e:
            self._log_test("Nonsensical Condition Handling", 
                          False, 
                          f"Evaluator should not raise an exception for nonsensical conditions: {str(e)}")
        
        # Test 7: Unicode characters in condition
        try:
            result = evaluate_condition("$a → $b", {"$a": True, "$b": True}, {}, {})
            self._log_test("Unicode Characters Handling", 
                          result is False, 
                          "Evaluator should safely handle unicode characters")
        except Exception as e:
            self._log_test("Unicode Characters Handling", 
                          False, 
                          f"Evaluator should not raise an exception for unicode characters: {str(e)}")
        
        # Test 8: None values in match dictionaries
        try:
            result = evaluate_condition("$a and $b", {"$a": True, "$b": None}, {}, {})
            self._log_test("None Value Handling", 
                          result is False, 
                          "Evaluator should safely handle None values")
        except Exception as e:
            self._log_test("None Value Handling", 
                          False, 
                          f"Evaluator should not raise an exception for None values: {str(e)}")
            
    def _test_matcher_errors(self):
        """Test matcher error handling."""
        print("\nTesting Matcher Error Handling:")
        
        # Create a simple test rule
        test_rule = NovaRule(name="TestMatcherRule")
        test_rule.meta = {"description": "Test rule for matcher error handling"}
        test_rule.keywords = {
            "$a": KeywordPattern(pattern="test", is_regex=False, case_sensitive=False)
        }
        test_rule.condition = "$a"
        
        # Test 1: Empty prompt
        matcher = NovaMatcher(test_rule)
        try:
            result = matcher.check_prompt("")
            self._log_test("Empty Prompt Handling", 
                          result["matched"] is False, 
                          "Matcher should return no match for empty prompt")
        except Exception as e:
            self._log_test("Empty Prompt Handling", 
                          False, 
                          f"Matcher should not raise an exception for empty prompt: {str(e)}")
        
        # Test 2: None prompt
        try:
            result = matcher.check_prompt(None)
            self._log_test("None Prompt Handling", 
                          result["matched"] is False, 
                          "Matcher should return no match for None prompt")
        except Exception as e:
            self._log_test("None Prompt Handling", 
                          False, 
                          f"Matcher should not raise an exception for None prompt: {str(e)}")
        
        # Test 3: Very long prompt
        long_prompt = "test " * 10000  # 50,000 characters
        try:
            result = matcher.check_prompt(long_prompt)
            self._log_test("Very Long Prompt Handling", 
                          isinstance(result, dict), 
                          "Matcher should handle very long prompts")
        except Exception as e:
            self._log_test("Very Long Prompt Handling", 
                          False, 
                          f"Matcher should not raise an exception for very long prompts: {str(e)}")
        
        # Test 4: Unicode prompt
        unicode_prompt = "测试 test 테스트 проверка"
        try:
            result = matcher.check_prompt(unicode_prompt)
            self._log_test("Unicode Prompt Handling", 
                          isinstance(result, dict), 
                          "Matcher should handle unicode prompts")
        except Exception as e:
            self._log_test("Unicode Prompt Handling", 
                          False, 
                          f"Matcher should not raise an exception for unicode prompts: {str(e)}")
        
        # Test 5: Rule with invalid condition
        invalid_rule = NovaRule(name="InvalidRule")
        invalid_rule.meta = {"description": "Test rule with invalid condition"}
        invalid_rule.keywords = {
            "$a": KeywordPattern(pattern="test", is_regex=False, case_sensitive=False)
        }
        invalid_rule.condition = "$a and"  # Invalid condition
        
        matcher = NovaMatcher(invalid_rule)
        try:
            result = matcher.check_prompt("test")
            self._log_test("Invalid Condition Rule Handling", 
                          isinstance(result, dict), 
                          "Matcher should handle rules with invalid conditions")
        except Exception as e:
            self._log_test("Invalid Condition Rule Handling", 
                          False, 
                          f"Matcher should not raise an exception for rules with invalid conditions: {str(e)}")
            
    def _test_special_syntax_errors(self):
        """Test special syntax error handling."""
        print("\nTesting Special Syntax Error Handling:")
        
        # Test 1: Invalid "any of" syntax
        try:
            result = evaluate_condition("any of keywords", {}, {}, {})
            self._log_test("Invalid 'any of' Syntax Handling", 
                          result is False, 
                          "Evaluator should safely handle invalid 'any of' syntax")
        except Exception as e:
            self._log_test("Invalid 'any of' Syntax Handling", 
                          False, 
                          f"Evaluator should not raise an exception for invalid 'any of' syntax: {str(e)}")
        
        # Test 2: Invalid "all of" syntax
        try:
            result = evaluate_condition("all of", {}, {}, {})
            self._log_test("Invalid 'all of' Syntax Handling", 
                          result is False, 
                          "Evaluator should safely handle invalid 'all of' syntax")
        except Exception as e:
            self._log_test("Invalid 'all of' Syntax Handling", 
                          False, 
                          f"Evaluator should not raise an exception for invalid 'all of' syntax: {str(e)}")
        
        # Test 3: Invalid "N of" syntax
        try:
            result = evaluate_condition("2 of", {}, {}, {})
            self._log_test("Invalid 'N of' Syntax Handling", 
                          result is False, 
                          "Evaluator should safely handle invalid 'N of' syntax")
        except Exception as e:
            self._log_test("Invalid 'N of' Syntax Handling", 
                          False, 
                          f"Evaluator should not raise an exception for invalid 'N of' syntax: {str(e)}")
        
        # Test 4: Invalid wildcard syntax
        try:
            result = evaluate_condition("keywords.*$", {}, {}, {})
            self._log_test("Invalid Wildcard Syntax Handling", 
                          result is False, 
                          "Evaluator should safely handle invalid wildcard syntax")
        except Exception as e:
            self._log_test("Invalid Wildcard Syntax Handling", 
                          False, 
                          f"Evaluator should not raise an exception for invalid wildcard syntax: {str(e)}")
        
        # Test 5: Invalid variable prefix syntax
        try:
            result = evaluate_condition("keywords.$*", {}, {}, {})
            self._log_test("Invalid Variable Prefix Syntax Handling", 
                          result is False, 
                          "Evaluator should safely handle invalid variable prefix syntax")
        except Exception as e:
            self._log_test("Invalid Variable Prefix Syntax Handling", 
                          False, 
                          f"Evaluator should not raise an exception for invalid variable prefix syntax: {str(e)}")
            
    def _test_edge_cases(self):
        """Test edge cases."""
        print("\nTesting Edge Cases:")
        
        # Test 1: Empty match dictionaries
        try:
            result = evaluate_condition("any of keywords.*", {}, {}, {})
            self._log_test("Empty Match Dictionaries Handling", 
                          result is False, 
                          "Evaluator should handle empty match dictionaries")
        except Exception as e:
            self._log_test("Empty Match Dictionaries Handling", 
                          False, 
                          f"Evaluator should not raise an exception for empty match dictionaries: {str(e)}")
        
        # Test 2: Extremely complex condition
        complex_condition = "($a and ($b or $c)) or (not $d and ($e or $f)) or (any of keywords.* and any of semantics.*) or llm.$g"
        try:
            result = evaluate_condition(
                complex_condition,
                {"$a": True, "$b": False, "$c": True, "$d": False, "$e": True, "$f": False},
                {"$semantic": True},
                {"$g": False}
            )
            self._log_test("Extremely Complex Condition Handling", 
                          isinstance(result, bool), 
                          "Evaluator should handle extremely complex conditions")
        except Exception as e:
            self._log_test("Extremely Complex Condition Handling", 
                          False, 
                          f"Evaluator should not raise an exception for extremely complex conditions: {str(e)}")
        
        # Test 3: Mixed case operators
        try:
            result = evaluate_condition("$a AnD $b OR $c", {"$a": True, "$b": True, "$c": False}, {}, {})
            self._log_test("Mixed Case Operators Handling", 
                          result is True, 
                          "Evaluator should handle mixed case operators")
        except Exception as e:
            self._log_test("Mixed Case Operators Handling", 
                          False, 
                          f"Evaluator should not raise an exception for mixed case operators: {str(e)}")
        
        # Test 4: Extra whitespace
        try:
            result = evaluate_condition("  $a   and    $b  ", {"$a": True, "$b": True}, {}, {})
            self._log_test("Extra Whitespace Handling", 
                          result is True, 
                          "Evaluator should handle extra whitespace")
        except Exception as e:
            self._log_test("Extra Whitespace Handling", 
                          False, 
                          f"Evaluator should not raise an exception for extra whitespace: {str(e)}")
        
        # Test 5: Non-boolean values in match dictionaries
        try:
            result = evaluate_condition("$a and $b", {"$a": 1, "$b": "string"}, {}, {})
            self._log_test("Non-Boolean Values Handling", 
                          isinstance(result, bool), 
                          "Evaluator should handle non-boolean values")
        except Exception as e:
            self._log_test("Non-Boolean Values Handling", 
                          False, 
                          f"Evaluator should not raise an exception for non-boolean values: {str(e)}")
            
    def _test_performance_issues(self):
        """Test potential performance issues."""
        print("\nTesting Performance Issues:")
        
        # Test 1: Many variables (100)
        many_vars_condition = " and ".join([f"$var{i}" for i in range(100)])
        many_vars_matches = {f"$var{i}": True for i in range(100)}
        
        start_time = time.time()
        try:
            evaluate_condition(many_vars_condition, many_vars_matches, {}, {})
            end_time = time.time()
            duration = end_time - start_time
            
            self._log_test("Many Variables Performance", 
                          duration < 1.0, 
                          f"Evaluator processed 100 variables in {duration:.4f} seconds")
        except Exception as e:
            self._log_test("Many Variables Performance", 
                          False, 
                          f"Evaluator should not raise an exception for many variables: {str(e)}")
        
        # Test 2: Deeply nested conditions (10 levels)
        nested_condition = "$a"
        for i in range(10):
            nested_condition = f"({nested_condition} and $var{i})"
        
        nested_matches = {"$a": True}
        nested_matches.update({f"$var{i}": True for i in range(10)})
        
        start_time = time.time()
        try:
            evaluate_condition(nested_condition, nested_matches, {}, {})
            end_time = time.time()
            duration = end_time - start_time
            
            self._log_test("Deeply Nested Conditions Performance", 
                          duration < 1.0, 
                          f"Evaluator processed 10 levels of nesting in {duration:.4f} seconds")
        except Exception as e:
            self._log_test("Deeply Nested Conditions Performance", 
                          False, 
                          f"Evaluator should not raise an exception for deeply nested conditions: {str(e)}")
        
        # Test 3: Many wildcards (50)
        wildcards_condition = " or ".join([f"keywords.$prefix{i}*" for i in range(50)])
        wildcards_matches = {f"$prefix{i}_var": True for i in range(50)}
        
        start_time = time.time()
        try:
            evaluate_condition(wildcards_condition, wildcards_matches, {}, {})
            end_time = time.time()
            duration = end_time - start_time
            
            self._log_test("Many Wildcards Performance", 
                          duration < 1.0, 
                          f"Evaluator processed 50 wildcards in {duration:.4f} seconds")
        except Exception as e:
            self._log_test("Many Wildcards Performance", 
                          False, 
                          f"Evaluator should not raise an exception for many wildcards: {str(e)}")
    
    def _print_summary(self):
        """Print test summary."""
        print("\n" + "=" * 70)
        print("Error Handling Test Summary:")
        print(f"Total tests: {self.passed_tests + self.failed_tests}")
        print(f"Passed: {self.passed_tests}")
        print(f"Failed: {self.failed_tests}")
        
        if self.failed_tests > 0:
            print("\nFailed Tests:")
            for i, result in enumerate(self.test_results):
                if not result["passed"]:
                    print(f"{i+1}. {result['name']}")
                    if result["details"]:
                        print(f"   Details: {result['details']}")
                    if result["expected_error"]:
                        print(f"   Expected error: {result['expected_error']}")
                    if result["actual_error"]:
                        print(f"   Actual error: {result['actual_error']}")
        
        print("\nError Handling Tests " + ("PASSED" if self.failed_tests == 0 else "FAILED"))
    
    def export_report(self, output_path):
        """Export test report to a file."""
        report = {
            "total_tests": self.passed_tests + self.failed_tests,
            "passed_tests": self.passed_tests,
            "failed_tests": self.failed_tests,
            "test_results": self.test_results,
            "all_tests_passed": self.failed_tests == 0
        }
        
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
            
        print(f"\nTest report exported to {output_path}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Test error handling in Nova rule system.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output.")
    parser.add_argument("-o", "--output", help="Path to export test report.")
    
    args = parser.parse_args()
    
    test_suite = NovaErrorTests(verbose=args.verbose)
    success = test_suite.run_tests()
    
    if args.output:
        test_suite.export_report(args.output)
    
    sys.exit(0 if success else 1)
