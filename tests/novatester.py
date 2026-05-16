"""
NOVA: The Prompt Pattern Matching Validation Test
Author: Claude
License: MIT License
Version: see nova._version
Description: Validation test suite for Nova rules and framework
"""

import sys
from typing import Dict, Any

# Add Nova module path if needed
# sys.path.append('/path/to/nova')

from nova.core.rules import NovaRule, KeywordPattern, SemanticPattern, LLMPattern
from nova.core.parser import NovaParser
from nova.core.matcher import NovaMatcher
from nova.evaluators.condition import evaluate_condition

class MockEvaluators:
    """
    Creates mock evaluators that simply return the expected results regardless of input.
    This is the most robust approach when you just want to test the condition evaluation logic.
    """
    
    @staticmethod
    def create_mock_matcher(rule, keyword_results, semantic_results, llm_results):
        """Create a NovaMatcher with mocked evaluators that return predefined results."""
        matcher = NovaMatcher(rule)
        
        # Replace keyword evaluator
        class MockKeywordEvaluator:
            def evaluate(self, pattern, text, key=None):
                if key in keyword_results:
                    return keyword_results[key]
                return False
                
            def compile_pattern(self, key, pattern):
                pass
                
        # Replace semantic evaluator - uses 0.1 threshold as required
        class MockSemanticEvaluator:
            def evaluate(self, pattern, text):
                # Try to extract variable name
                var_name = None
                
                if hasattr(pattern, 'pattern'):
                    # Try to match the pattern text to our known variables
                    pattern_str = pattern.pattern
                    for key in semantic_results:
                        # Direct match if the key name is in the pattern
                        # Remove $ to compare with pattern text
                        key_without_dollar = key[1:] if key.startswith('$') else key
                        if key_without_dollar in pattern_str:
                            var_name = key
                            break
                
                # If no match found, try using the object's position in memory as a key
                if var_name is None:
                    var_name = str(pattern)
                    # Last resort: just return the first semantic match if any exist
                    if var_name not in semantic_results and semantic_results:
                        var_name = next(iter(semantic_results))
                
                if var_name and var_name in semantic_results:
                    # Always use 0.1 as the score, as requested
                    return semantic_results[var_name], 0.1
                return False, 0.0
        
        # Replace LLM evaluator
        # Replace LLM evaluator
        class MockLLMEvaluator:
            def evaluate_prompt(self, prompt, text, temperature=0.1):
                # Find a matching key in our predefined results
                var_name = None
                
                # Try to match prompt to a variable name
                for key in llm_results:
                    key_without_dollar = key[1:] if key.startswith('$') else key
                    if key_without_dollar in prompt:
                        var_name = key
                        break
                
                # If no match found, use the first LLM match if any exist
                if var_name is None and llm_results:
                    var_name = next(iter(llm_results))
                
                if var_name and var_name in llm_results:
                    # Return the predefined result with a high confidence
                    return llm_results[var_name], 0.9, {"detail": "Mock evaluation", "temperature": temperature}
                return False, 0.0, {"detail": "No match", "temperature": temperature}
        
        matcher.keyword_evaluator = MockKeywordEvaluator()
        matcher.semantic_evaluator = MockSemanticEvaluator()
        matcher.llm_evaluator = MockLLMEvaluator()
        
        return matcher

class NovaValidationTest:
    """
    Validation test suite for Nova rules and framework.
    Tests rule parsing, condition evaluation, and overall matching.
    """
    
    def __init__(self):
        """Initialize the test suite."""
        self.parser = NovaParser()
        self.test_results = []
        self.success_count = 0
        self.fail_count = 0
        
    def run_tests(self):
        """Run all validation tests."""
        print("Starting Nova Validation Tests...")
        print("=" * 70)
        
        # Test basic condition evaluation
        self._test_basic_condition_eval()
        
        # Test complex condition evaluation
        self._test_complex_condition_eval()
        
        # Test special syntax handling
        self._test_special_syntax()
        
        # Test rule parsing
        self._test_rule_parsing()
        
        # Test end-to-end matching
        self._test_end_to_end_matching()
        
        # Test real-world examples
        self._test_real_world_examples()
        
        # Print summary
        print("\nTest Summary:")
        print(f"Total Tests: {self.success_count + self.fail_count}")
        print(f"Passed: {self.success_count}")
        print(f"Failed: {self.fail_count}")
        
        # Return whether all tests passed
        return self.fail_count == 0
        
    def _log_test(self, name: str, passed: bool, details: str = ""):
        """Log a test result."""
        status = "PASSED" if passed else "FAILED"
        print(f"Test: {name} - {status}")
        if details and not passed:
            print(f"  Details: {details}")
        
        self.test_results.append({
            "name": name,
            "passed": passed,
            "details": details
        })
        
        if passed:
            self.success_count += 1
        else:
            self.fail_count += 1
            
    def _test_basic_condition_eval(self):
        """Test basic condition evaluation functionality."""
        print("\nTesting Basic Condition Evaluation:")
        
        # Simple AND condition
        result = self._evaluate_test_condition(
            "$a and $b",
            {"$a": True, "$b": True},
            {},
            {}
        )
        self._log_test("Simple AND (True + True)", 
                      result is True,
                      f"Expected True, got {result}")
        
        result = self._evaluate_test_condition(
            "$a and $b",
            {"$a": True, "$b": False},
            {},
            {}
        )
        self._log_test("Simple AND (True + False)", 
                      result is False,
                      f"Expected False, got {result}")
        
        # Simple OR condition
        result = self._evaluate_test_condition(
            "$a or $b",
            {"$a": False, "$b": True},
            {},
            {}
        )
        self._log_test("Simple OR (False + True)", 
                      result is True,
                      f"Expected True, got {result}")
        
        result = self._evaluate_test_condition(
            "$a or $b",
            {"$a": False, "$b": False},
            {},
            {}
        )
        self._log_test("Simple OR (False + False)", 
                      result is False,
                      f"Expected False, got {result}")
        
        # NOT condition
        result = self._evaluate_test_condition(
            "not $a",
            {"$a": False},
            {},
            {}
        )
        self._log_test("Simple NOT (False)", 
                      result is True,
                      f"Expected True, got {result}")
        
        # Parentheses and operator precedence
        result = self._evaluate_test_condition(
            "$a and ($b or $c)",
            {"$a": True, "$b": False, "$c": True},
            {},
            {}
        )
        self._log_test("Parentheses and Precedence", 
                      result is True,
                      f"Expected True, got {result}")
        
        # Multiple ANDs and ORs
        result = self._evaluate_test_condition(
            "$a and $b or $c and $d",
            {"$a": True, "$b": True, "$c": False, "$d": True},
            {},
            {}
        )
        self._log_test("Multiple ANDs and ORs", 
                      result is True,
                      f"Expected True, got {result}")
        
        # Section prefixed variables
        result = self._evaluate_test_condition(
            "keywords.$a and semantics.$b",
            {"$a": True},
            {"$b": True},
            {}
        )
        self._log_test("Section Prefixed Variables", 
                      result is True,
                      f"Expected True, got {result}")
        
    def _test_complex_condition_eval(self):
        """Test more complex condition evaluation."""
        print("\nTesting Complex Condition Evaluation:")
        
        # Condition with multiple operators and parentheses
        result = self._evaluate_test_condition(
            "($a and $b) or ($c and not $d)",
            {"$a": False, "$b": True, "$c": True, "$d": False},
            {},
            {}
        )
        self._log_test("Complex Operators and Parentheses", 
                      result is True,
                      f"Expected True, got {result}")
        
        # Mixed section references
        result = self._evaluate_test_condition(
            "keywords.$a and semantics.$b or llm.$c",
            {"$a": False},
            {"$b": False},
            {"$c": True}
        )
        self._log_test("Mixed Section References", 
                      result is True,
                      f"Expected True, got {result}")
        
        # Nested parentheses
        result = self._evaluate_test_condition(
            "(($a or $b) and ($c or $d)) or $e",
            {"$a": True, "$b": False, "$c": True, "$d": False, "$e": False},
            {},
            {}
        )
        self._log_test("Nested Parentheses", 
                      result is True,
                      f"Expected True, got {result}")
        
        # Missing variables
        result = self._evaluate_test_condition(
            "$a and $nonexistent",
            {"$a": True},
            {},
            {}
        )
        self._log_test("Missing Variables", 
                      result is False,
                      f"Expected False, got {result}")
        
    def _test_special_syntax(self):
        """Test special syntax handling."""
        print("\nTesting Special Syntax:")
        
        # any of keywords.*
        result = self._evaluate_test_condition(
            "any of keywords.*",
            {"$a": True, "$b": False},
            {},
            {}
        )
        self._log_test("any of keywords.* (with matches)", 
                      result is True,
                      f"Expected True, got {result}")
        
        result = self._evaluate_test_condition(
            "any of keywords.*",
            {"$a": False, "$b": False},
            {},
            {}
        )
        self._log_test("any of keywords.* (no matches)", 
                      result is False,
                      f"Expected False, got {result}")
        
        # any of semantics.*
        result = self._evaluate_test_condition(
            "any of semantics.*",
            {},
            {"$a": True, "$b": False},
            {}
        )
        self._log_test("any of semantics.* (with matches)", 
                      result is True,
                      f"Expected True, got {result}")
        
        # any of llm.*
        result = self._evaluate_test_condition(
            "any of llm.*",
            {},
            {},
            {"$a": True, "$b": False}
        )
        self._log_test("any of llm.* (with matches)", 
                      result is True,
                      f"Expected True, got {result}")
        
        # Complex with special syntax
        result = self._evaluate_test_condition(
            "(any of keywords.* and any of semantics.*) or llm.$a",
            {"$k": True},
            {"$s": True},
            {"$a": False}
        )
        self._log_test("Complex with Special Syntax (true branch)", 
                      result is True,
                      f"Expected True, got {result}")
        
        result = self._evaluate_test_condition(
            "(any of keywords.* and any of semantics.*) or llm.$a",
            {"$k": False},
            {"$s": True},
            {"$a": True}
        )
        self._log_test("Complex with Special Syntax (alt branch)", 
                      result is True,
                      f"Expected True, got {result}")
        
        result = self._evaluate_test_condition(
            "(any of keywords.* and any of semantics.*) or llm.$a",
            {"$k": False},
            {"$s": True},
            {"$a": False}
        )
        self._log_test("Complex with Special Syntax (should fail)", 
                      result is False,
                      f"Expected False, got {result}")
        
    def _test_rule_parsing(self):
        """Test rule parsing functionality."""
        print("\nTesting Rule Parsing:")
        
        # Simple rule
        rule_str = """
        rule TestRule
        {
            meta:
                description = "Test rule for validation"
                author = "Claude"
                version = "1.0.0"
                
            keywords:
                $a = "test"
                $b = "example"
                
            semantics:
                $c = "asking about test examples" (0.5)
                
            llm:
                $d = "Determine if this is a test query" (0.7)
                
            condition:
                $a and $b or $c
        }
        """
        
        try:
            rule = self.parser.parse(rule_str)
            self._log_test("Basic Rule Parsing", 
                          rule.name == "TestRule",
                          f"Expected rule name 'TestRule', got '{rule.name}'")
            
            self._log_test("Keywords Parsing", 
                          "$a" in rule.keywords and "$b" in rule.keywords,
                          f"Expected keywords $a and $b, got {list(rule.keywords.keys())}")
            
            self._log_test("Semantics Parsing", 
                          "$c" in rule.semantics,
                          f"Expected semantic $c, got {list(rule.semantics.keys())}")
            
            self._log_test("LLM Parsing", 
                          "$d" in rule.llms,
                          f"Expected LLM pattern $d, got {list(rule.llms.keys())}")
            
            self._log_test("Condition Parsing", 
                          rule.condition == "$a and $b or $c",
                          f"Expected condition '$a and $b or $c', got '{rule.condition}'")
            
        except Exception as e:
            self._log_test("Rule Parsing Exception Handling", 
                          False,
                          f"Parser threw exception: {str(e)}")
        
        # Rule with special syntax
        rule_str = """
        rule SpecialSyntaxRule
        {
            meta:
                description = "Rule with special syntax for validation"
                author = "Claude"
                version = "1.0.0"
                
            keywords:
                $a = "test"
                $b = "example"
                
            semantics:
                $c = "asking about test examples" (0.1)
                
            llm:
                $d = "Determine if this is a test query" (0.7)
                
            condition:
                (any of keywords.* and any of semantics.*) or llm.$d
        }
        """
        
        try:
            rule = self.parser.parse(rule_str)
            self._log_test("Special Syntax Rule Parsing", 
                          rule.condition == "(any of keywords.* and any of semantics.*) or llm.$d",
                          f"Expected condition with special syntax, got '{rule.condition}'")
            
        except Exception as e:
            self._log_test("Special Syntax Rule Parsing", 
                          False,
                          f"Parser threw exception: {str(e)}")
        
    def _test_end_to_end_matching(self):
        """Test end-to-end rule matching."""
        print("\nTesting End-to-End Matching:")
        
        # Create a simple test rule
        test_rule = NovaRule(name="TestEndToEndRule")
        test_rule.meta = {"description": "Test rule for end-to-end matching"}
        test_rule.keywords = {
            "$keyword1": KeywordPattern(pattern="test", is_regex=False, case_sensitive=False),
            "$keyword2": KeywordPattern(pattern="example", is_regex=False, case_sensitive=False)
        }
        test_rule.semantics = {
            "$semantic1": SemanticPattern(pattern="asking about tests", threshold=0.5)
        }
        test_rule.llms = {
            "$llm1": LLMPattern(pattern="Determine if this is a test query", threshold=0.7)
        }
        
        # Test various conditions
        conditions_to_test = [
            ("$keyword1", True, "Simple keyword match"),
            ("$keyword1 and $keyword2", True, "AND keywords"),
            ("$keyword1 and not $nonexistent", True, "Nonexistent variable"),
            ("$keyword1 and semantics.$semantic1", True, "Cross-section reference"),
            ("any of keywords.*", True, "any of keywords.*"),
            ("(any of keywords.* and any of semantics.*) or llm.$llm1", True, "Complex with special syntax")
        ]
        
        # Test prompt
        test_prompt = "This is a test example query about tests."
        
        # Mock evaluation results
        expected_evaluator_results = {
            "keywords": {"$keyword1": True, "$keyword2": True},
            "semantics": {"$semantic1": True},
            "llm": {"$llm1": True}
        }
        
        # Test each condition
        for condition, expected_match, desc in conditions_to_test:
            test_rule.condition = condition
            result = self._test_matching(test_rule, test_prompt, expected_evaluator_results)
            self._log_test(f"End-to-End Matching: {desc}", 
                          result == expected_match,
                          f"Expected {expected_match}, got {result} for condition: {condition}")
    
    def _test_real_world_examples(self):
        """Test real-world examples from the provided rules."""
        print("\nTesting Real-World Examples:")
        
        # Test WebShellExploitRule
        webshell_rule_str = """
        rule WebShellExploitRule
        {
            meta:
                description = "Detects queries about using SQLMap to upload web shells"
                author = "Thomas Roccia"
                version = "1.0.0"
                category = "vulnerability/webshell"
                severity = "high"
                attack_category = "LLM-assisted vulnerability research"
            
            keywords:
                $sqlmap = "sqlmap"
                $webshell = "web shell"
                $webshell2 = "webshell"
                $shell = "shell"
                $upload = "upload"
                $inject = "inject"
                $execute = "execute"
                $rce = "RCE"
                $sql_injection = "SQL injection"
                $sqli = "SQLi"
                $target = "target"
                $server = "server"
            
            semantics:
                $webshell_inquiry = "seeking information on uploading malicious web shells" (0.1)
                $sqlmap_misuse = "asking for guidance on misusing SQLMap for unauthorized access" (0.1)
            
            llm:
                $shell_upload_check = "Evaluate if this query is requesting information on using SQLMap to upload web shells or gain unauthorized remote access" (0.8)
            
            condition:
                $sqlmap and 
                ($webshell or $webshell2 or $shell) and
                ($upload or $inject) and
                ($execute or $rce or $sql_injection or $sqli) and
                ($target or $server) and
                (any of semantics.*) and llm.$shell_upload_check
        }
        """
        
        # Create rule from string
        try:
            webshell_rule = self.parser.parse(webshell_rule_str)
            
            # Test positive case
            positive_prompt = "How can I use sqlmap to upload a web shell to target server? I want to inject a shell that can execute SQL injection commands."
            positive_results = {
                "keywords": {
                    "$sqlmap": True, 
                    "$webshell": True, 
                    "$webshell2": False, 
                    "$shell": True,
                    "$upload": True,
                    "$inject": True,
                    "$execute": True,
                    "$rce": False,
                    "$sql_injection": True,
                    "$sqli": False,
                    "$target": True,
                    "$server": True
                },
                "semantics": {
                    "$webshell_inquiry": True, 
                    "$sqlmap_misuse": True
                },
                "llm": {
                    "$shell_upload_check": True
                }
            }
            
            positive_match = self._test_matching(webshell_rule, positive_prompt, positive_results)
            self._log_test("WebShellExploitRule - Positive Case", 
                          positive_match is True,
                          "Should match a clear sqlmap webshell upload attempt")
            
            # Test negative case with RCE only
            negative_prompt = "I'm interested in contributing to open source security tools. What would be involved in developing modules for penetration testing frameworks?"
            negative_results = {
                "keywords": {
                    "$sqlmap": False, 
                    "$webshell": False, 
                    "$webshell2": False, 
                    "$shell": False,
                    "$upload": False,
                    "$inject": False,
                    "$execute": False,
                    "$rce": True,  # Only RCE matches
                    "$sql_injection": False,
                    "$sqli": False,
                    "$target": False,
                    "$server": False
                },
                "semantics": {
                    "$webshell_inquiry": False, 
                    "$sqlmap_misuse": False
                },
                "llm": {
                    "$shell_upload_check": False
                }
            }
            
            negative_match = self._test_matching(webshell_rule, negative_prompt, negative_results)
            self._log_test("WebShellExploitRule - RCE Only Negative Case", 
                          negative_match is False,
                          "Should not match when only RCE keyword matches")
            
        except Exception as e:
            self._log_test("WebShellExploitRule Test", 
                          False,
                          f"Test threw exception: {str(e)}")
        
        # Test SecurityToolExtensionRule
        security_tool_rule_str = """
        rule SecurityToolExtensionRule
        {
            meta:
                description = "Detects requests for help developing extensions for cybersecurity tools"
                author = "Thomas Roccia"
                version = "1.0.0"
                category = "scripting/security_tools"
                severity = "medium"
                attack_category = "LLM-enhanced scripting techniques"
            
            keywords:
                $develop = "develop"
                $create = "create"
                $debug = "debug"
                $extension = "extension"
                $plugin = "plugin"
                $module = "module"
                $addon = "addon"
                $tool = "tool"
                $cybersecurity = "cybersecurity"
                $security = "security"
                $pentest = "pentest"
                $penetration = "penetration"
                $metasploit = "Metasploit"
                $burp = "Burp"
                $nmap = "Nmap"
                $wireshark = "Wireshark"
            
            semantics:
                $tool_dev_request = "requesting assistance with developing security tool extensions" (0.1)
                $security_tool_modification = "seeking help modifying or extending cybersecurity tools" (0.1)
            
            llm:
                $extension_check = "Analyze if this query is asking for help developing or debugging an extension for a cybersecurity or penetration testing tool" (0.7)
            
            condition:
                (any of keywords.* and any of semantics.*) or llm.$extension_check
        }
        """
        
        # Create matcher with SecurityToolExtensionRule
        try:
            security_tool_rule = self.parser.parse(security_tool_rule_str)
            
            # Test positive case
            positive_prompt = "I'm interested in contributing to open source security tools. What would be involved in developing modules for penetration testing frameworks?"
            positive_results = {
                "keywords": {
                    "$develop": True, 
                    "$create": False, 
                    "$debug": False, 
                    "$extension": False,
                    "$plugin": False,
                    "$module": True,
                    "$addon": False,
                    "$tool": False,
                    "$cybersecurity": False,
                    "$security": True,
                    "$pentest": False,
                    "$penetration": True,
                    "$metasploit": False,
                    "$burp": False,
                    "$nmap": False,
                    "$wireshark": False
                },
                "semantics": {
                    "$tool_dev_request": True, 
                    "$security_tool_modification": True
                },
                "llm": {
                    "$extension_check": True
                }
            }
            
            positive_match = self._test_matching(security_tool_rule, positive_prompt, positive_results)
            self._log_test("SecurityToolExtensionRule - Positive Case", 
                          positive_match is True,
                          "Should match a security tool extension development request")
            
            # Test case with only LLM match
            llm_only_prompt = "What's involved in building add-ons for security products?"
            llm_only_results = {
                "keywords": {
                    "$develop": False, 
                    "$create": False, 
                    "$debug": False, 
                    "$extension": False,
                    "$plugin": False,
                    "$module": False,
                    "$addon": False,
                    "$tool": False,
                    "$cybersecurity": False,
                    "$security": False,
                    "$pentest": False,
                    "$penetration": False,
                    "$metasploit": False,
                    "$burp": False,
                    "$nmap": False,
                    "$wireshark": False
                },
                "semantics": {
                    "$tool_dev_request": False, 
                    "$security_tool_modification": False
                },
                "llm": {
                    "$extension_check": True
                }
            }
            
            llm_only_match = self._test_matching(security_tool_rule, llm_only_prompt, llm_only_results)
            self._log_test("SecurityToolExtensionRule - LLM Only Case", 
                          llm_only_match is True,
                          "Should match when only the LLM check is positive (second part of OR condition)")
            
        except Exception as e:
            self._log_test("SecurityToolExtensionRule Test", 
                          False,
                          f"Test threw exception: {str(e)}")
    
    def _evaluate_test_condition(self, condition: str, 
                                keyword_matches: Dict[str, bool],
                                semantic_matches: Dict[str, bool],
                                llm_matches: Dict[str, bool]) -> bool:
        """Helper to evaluate a test condition."""
        try:
            return evaluate_condition(condition, keyword_matches, semantic_matches, llm_matches)
        except Exception as e:
            print(f"Error evaluating condition '{condition}': {str(e)}")
            return None
    
    def _test_matching(self, rule: NovaRule, prompt: str, expected_results: Dict[str, Any]) -> bool:
        """Test matching a prompt against a rule with predefined evaluation results."""
        # Use the MockEvaluators helper to create a matcher with predefined results
        mock_matcher = MockEvaluators.create_mock_matcher(
            rule,
            expected_results.get("keywords", {}),
            expected_results.get("semantics", {}),
            expected_results.get("llm", {})
        )
        
        # Run the matcher
        result = mock_matcher.check_prompt(prompt)
        
        # Return whether it matched
        return result["matched"]


if __name__ == "__main__":
    # Run the validation tests
    test_suite = NovaValidationTest()
    success = test_suite.run_tests()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)