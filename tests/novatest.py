"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia 
twitter: @fr0gger_
License: MIT License
Version: see nova._version
Description: Test suite for Nova framework
"""

import argparse
from nova.core.parser import NovaParser
from nova.core.matcher import NovaMatcher

# Set API key for testing if you want to use real LLM calls
# os.environ["OPENAI_API_KEY"] = "your-api-key-here"


def run_test(rule_text, prompt, expected_match, description, verbose=False):
    """Run a test with simplified output."""
    parser = NovaParser()
    rule = parser.parse(rule_text)
    
    matcher = NovaMatcher(rule)
    result = matcher.check_prompt(prompt)
    
    match_status = "✓" if result['matched'] == expected_match else "✗"
    
    # Basic output
    print(f"\n=== Test: {description} ===")
    print(f"Rule: {rule.name}")
    
    # Only show author from metadata
    if rule.meta and 'author' in rule.meta:
        print(f"Author: {rule.meta['author']}")
    
    print(f"Prompt: '{prompt}'")
    print(f"Match: {result['matched']} (Expected: {expected_match}) {match_status}")
    
    # Only show detailed debug info if verbose is enabled
    if verbose:
        print("\n--- Debug Info ---")
        
        if result['matching_keywords']:
            print(f"Matching keywords: {result['matching_keywords']}")
            
        if result['matching_semantics']:
            print(f"Matching semantics: {result['matching_semantics']}")
            
        if 'matching_llm' in result and result['matching_llm']:
            print(f"Matching LLM prompts: {result['matching_llm']}")
        
        if 'debug' in result and 'all_keyword_matches' in result['debug']:
            print("\nKeyword variables in condition:")
            for k, v in result['debug']['all_keyword_matches'].items():
                print(f"  keywords.{k}: {v}")
        
        if 'debug' in result and 'all_semantic_matches' in result['debug']:
            print("\nSemantic variables in condition:")
            for k, v in result['debug']['all_semantic_matches'].items():
                print(f"  semantics.{k}: {v}")
        
        if 'debug' in result and 'all_llm_matches' in result['debug']:
            print("\nLLM variables in condition:")
            for k, v in result['debug']['all_llm_matches'].items():
                print(f"  llm.{k}: {v}")
        
        if 'semantic_scores' in result:
            print("\nSemantic scores:")
            for k, v in result['semantic_scores'].items():
                print(f"  {k}: {v:.4f}")
    
    return result['matched'] == expected_match


def run_simplified_tests(verbose=False):
    """Run simplified tests with minimal metadata."""
    results = []
    
    # Test 1: Content Classification
    test1_rule = """rule ContentClassification
    {
        meta:
            description = "Classifies content types"
            author = "Security Team"
            
        keywords:
            $tech = "technology"
            $science = "science"
            $finance = "finance"
        
        condition:
            keywords.$tech or keywords.$science or keywords.$finance
    }"""
    
    test1_prompt = "The latest technology innovations are revolutionizing science."
    results.append(run_test(test1_rule, test1_prompt, True, "Content Classification", verbose))
    
    # Test 2: NSFW Detection
    test2_rule = """rule NSFWDetection
    {
        meta:
            description = "Detects NSFW content"
            author = "Moderation Team"
            
        keywords:
            $explicit = "explicit content"
            $adult = "adult material"
        
        llm:
            $nsfw_check = "Determine if this contains NSFW material" (0.7)
        
        condition:
            keywords.$explicit or keywords.$adult or llm.$nsfw_check
    }"""
    
    test2_prompt = "This website contains explicit content not suitable for minors."
    results.append(run_test(test2_rule, test2_prompt, True, "NSFW Detection", verbose))
    
    # Test 3: Security Alert
    test3_rule = """rule SecurityAlert
    {
        meta:
            description = "Identifies security threats"
            author = "Cybersecurity Team"
            
        keywords:
            $security = "security"
            $breach = "breach"
            $unauthorized = "unauthorized"
        
        llm:
            $threat = "Determine if this describes a security threat" (0.6)
        
        condition:
            (keywords.$security or keywords.$breach or keywords.$unauthorized) and llm.$threat
    }"""
    
    test3_prompt = "SECURITY ALERT: We detected unauthorized access attempts on your account."
    results.append(run_test(test3_rule, test3_prompt, True, "Security Alert", verbose))
    
    # Test 4: Customer Service Intent
    test4_rule = """rule CustomerServiceIntent
    {
        meta:
            description = "Identifies support requests"
            author = "Support Team"
            
        keywords:
            $help = "help"
            $support = "support"
            $issue = "issue"
        
        llm:
            $help_request = "Determine if this is a request for help" (0.6)
        
        condition:
            (keywords.$help or keywords.$support or keywords.$issue) and llm.$help_request
    }"""
    
    test4_prompt = "I need help with an issue. Can your support team assist me?"
    results.append(run_test(test4_rule, test4_prompt, True, "Customer Service Intent", verbose))
    
    # Test 5: Data Privacy Concerns
    test5_rule = """rule DataPrivacyConcern
    {
        meta:
            description = "Identifies privacy concerns"
            author = "Privacy Team"
            
        keywords:
            $data = "data"
            $privacy = "privacy"
            $delete = "delete my data"
        
        llm:
            $privacy_concern = "Check if this is about data privacy" (0.6)
        
        condition:
            (keywords.$data or keywords.$privacy or keywords.$delete) and llm.$privacy_concern
    }"""
    
    test5_prompt = "I want to delete my data and have privacy concerns about your practices."
    results.append(run_test(test5_rule, test5_prompt, True, "Data Privacy Concerns", verbose))
    
    # Test 6: Phishing Detection
    test6_rule = """rule PhishingDetection
    {
        meta:
            description = "Detects phishing attempts"
            author = "Security Team"
            
        keywords:
            $account = "account"
            $verify = "verify"
            $urgent = "urgent"
            $click = "click"
        
        llm:
            $phishing = "Determine if this is a phishing attempt" (0.7)
        
        condition:
            (keywords.$account or keywords.$verify or keywords.$urgent or keywords.$click) and llm.$phishing
    }"""
    
    test6_prompt = "URGENT: Your account needs verification. Click this link immediately to verify."
    results.append(run_test(test6_rule, test6_prompt, True, "Phishing Detection", verbose))
    
    # Test 7: Sales Opportunity
    test7_rule = """rule SalesOpportunity
    {
        meta:
            description = "Identifies sales leads"
            author = "Sales Team"
            
        keywords:
            $buy = "buy"
            $price = "price"
            $interested = "interested in"
        
        llm:
            $purchase_intent = "Check if this shows purchase intent" (0.7)
        
        condition:
            (keywords.$buy or keywords.$price or keywords.$interested) and llm.$purchase_intent
    }"""
    
    test7_prompt = "I'm interested in buying your product. What's the price?"
    results.append(run_test(test7_rule, test7_prompt, True, "Sales Opportunity", verbose))
    
    # Test 8: Sensitive Information
    test8_rule = """rule SensitiveInfo
    {
        meta:
            description = "Identifies sensitive information"
            author = "InfoSec Team"
            
        keywords:
            $confidential = "confidential"
            $secret = "secret"
            $sensitive = "sensitive"
        
        condition:
            keywords.$confidential or keywords.$secret or keywords.$sensitive
    }"""
    
    test8_prompt = "CONFIDENTIAL: This document contains sensitive information."
    results.append(run_test(test8_rule, test8_prompt, True, "Sensitive Information", verbose))
    
    # Test 9: Emergency Alert
    test9_rule = """rule EmergencyAlert
    {
        meta:
            description = "Identifies emergency situations"
            author = "Emergency Team"
            
        keywords:
            $emergency = "emergency"
            $urgent = "urgent"
            $immediate = "immediate"
        
        semantics:
            $emergency_situation = "emergency situation" (0.1)
        
        condition:
            (keywords.$emergency or keywords.$urgent or keywords.$immediate) and semantics.$emergency_situation
    }"""
    
    test9_prompt = "EMERGENCY: Immediate assistance required. This is an urgent situation."
    results.append(run_test(test9_rule, test9_prompt, True, "Emergency Alert", verbose))
    
    # Test 10: Negative Test Case
    test10_rule = """rule TechnicalDiscussion
    {
        meta:
            description = "Identifies technical discussions"
            author = "Engineering Team"
            
        keywords:
            $code = "code"
            $bug = "bug"
            $error = "error"
        
        llm:
            $technical = "Check if this is a technical discussion" (0.6)
        
        condition:
            (keywords.$code or keywords.$bug or keywords.$error) and llm.$technical
    }"""
    
    test10_prompt = "I enjoyed the movie last night. The weather is nice today."
    results.append(run_test(test10_rule, test10_prompt, False, "Negative Test Case", verbose))
    
    # Test 11: Case Sensitive Keywords
    test11_rule = """rule CaseSensitiveMatch
    {
        meta:
            description = "Tests case sensitive matching"
            author = "Test Team"
            
        keywords:
            $sensitive = "Python case:true"
            $insensitive = "python"
        
        condition:
            keywords.$sensitive or keywords.$insensitive
    }"""
    
    # This should match only the insensitive keyword
    test11_prompt = "I'm learning python programming."
    results.append(run_test(test11_rule, test11_prompt, True, "Case Sensitive Match - Lowercase", verbose))
    
    # This should match both keywords
    test11_prompt_2 = "I'm learning Python programming."
    results.append(run_test(test11_rule, test11_prompt_2, True, "Case Sensitive Match - Proper Case", verbose))
    
    # Test 12: Regex Pattern Matching
    test12_rule = r"""rule RegexPatternMatch
    {
        meta:
            description = "Tests regex pattern matching"
            author = "Test Team"
            
        keywords:
            $email = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/
            $phone = /\d{3}[-.\s]?\d{3}[-.\s]?\d{4}/
            $ip = /(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})/
        
        condition:
            keywords.$email or keywords.$phone or keywords.$ip
    }"""
    
    test12_prompt = "Contact me at test@example.com or call 555-123-4567."
    results.append(run_test(test12_rule, test12_prompt, True, "Regex Pattern Match - Email and Phone", verbose))
    
    test12_prompt_2 = "Server IP address is 192.168.1.1"
    results.append(run_test(test12_rule, test12_prompt_2, True, "Regex Pattern Match - IP Address", verbose))
    
    # Test 13: Case Sensitive Regex
    test13_rule = r"""rule CaseSensitiveRegex
    {
        meta:
            description = "Tests case sensitive regex"
            author = "Test Team"
            
        keywords:
            $sensitive = /Python case:true/
            $protocol = /https?:\/\//
        
        condition:
            keywords.$sensitive or keywords.$protocol
    }"""
    
    test13_prompt = "PYTHON is different from python in this test."
    results.append(run_test(test13_rule, test13_prompt, False, "Case Sensitive Regex - No Match", verbose))
    
    test13_prompt_2 = "Python is case sensitive here, and so is https://example.com"
    results.append(run_test(test13_rule, test13_prompt_2, True, "Case Sensitive Regex - With Match", verbose))
    
    # Summarize test results
    passed = sum(results)
    total = len(results)
    print("\n=== Test Summary ===")
    print(f"Passed: {passed}/{total} tests ({passed/total*100:.0f}%)")


if __name__ == "__main__":
    # Add command line argument for verbose mode
    parser = argparse.ArgumentParser(description='Run Nova Rule tests')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output with debugging information')
    args = parser.parse_args()
    
    run_simplified_tests(verbose=args.verbose)
