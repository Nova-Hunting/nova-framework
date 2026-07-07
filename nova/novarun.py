#!/usr/bin/env python3
# ruff: noqa: E402
"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia 
twitter: @fr0gger_
License: MIT License
Version: see nova._version
Description: Command-line tool for running Nova rules against prompts
"""

# Filter out the specific FutureWarning about clean_up_tokenization_spaces
import warnings
warnings.filterwarnings("ignore", message=".*clean_up_tokenization_spaces.*")

import argparse
import os
import sys
from typing import Dict, Any, Optional, List
import colorama
from colorama import Fore, Back

# Import Nova components
try:
    from nova.core.parser import NovaParser, NovaRuleFileParser
    from nova.core.matcher import NovaMatcher
    from nova.utils.config import get_config
    from nova.evaluators.llm import get_validated_evaluator
except ImportError:
    print("Error: Nova package not found in PYTHONPATH.")
    print("Make sure Nova is installed or set your PYTHONPATH correctly.")
    sys.exit(1)

# Initialize colorama
colorama.init(autoreset=True)

SUPPORTED_LLM_PROVIDERS = ['openai', 'anthropic', 'azure', 'ollama', 'groq', 'openrouter']

CONFIG_API_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "azure_openai": "AZURE_OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _config_value(section: Dict[str, Any], *keys: str) -> Any:
    """Return the first non-empty config value matching any key."""
    if not isinstance(section, dict):
        return None

    lower_section = {str(key).lower(): value for key, value in section.items()}
    for key in keys:
        value = lower_section.get(key.lower())
        if value not in (None, ""):
            return value

    return None


def _normalize_llm_provider(provider: Any) -> str:
    """Normalize config provider names to CLI evaluator names."""
    provider_name = str(provider).strip().lower().replace("-", "_")
    if provider_name == "azure_openai":
        provider_name = "azure"

    if provider_name not in SUPPORTED_LLM_PROVIDERS:
        expected = ", ".join(SUPPORTED_LLM_PROVIDERS)
        raise ValueError(f"Unsupported LLM provider '{provider}'. Expected one of: {expected}")

    return provider_name


def apply_config_to_args(args: argparse.Namespace) -> None:
    """
    Apply --config values to CLI execution.

    Explicit CLI flags stay first, environment variables stay ahead of file
    values, and file defaults are not treated as explicit model choices.
    """
    if not args.config:
        return

    config = get_config(args.config)
    llm_config = config.get_section("llm")
    api_keys = config.get_section("api_keys")

    if args.llm is None:
        args.llm = _normalize_llm_provider(_config_value(llm_config, "provider") or "openai")

    if args.model is None:
        configured_model = config.get_file_value("llm", "model")
        if configured_model not in (None, ""):
            os.environ.setdefault("NOVA_LLM_MODEL", str(configured_model))

    for config_key, env_name in CONFIG_API_KEY_ENV.items():
        configured_key = _config_value(api_keys, config_key)
        if configured_key not in (None, ""):
            os.environ.setdefault(env_name, str(configured_key))

    endpoint = _config_value(llm_config, "azure_endpoint", "azure_openai_endpoint", "endpoint")
    if endpoint not in (None, ""):
        os.environ.setdefault("AZURE_OPENAI_ENDPOINT", str(endpoint))

    host = _config_value(llm_config, "ollama_host", "host")
    if host not in (None, ""):
        os.environ.setdefault("OLLAMA_HOST", str(host))


def load_rule_file(file_path: str) -> str:
    """
    Load a Nova rule from a file.
    
    Args:
        file_path: Path to the rule file
        
    Returns:
        String containing the rule definition
        
    Raises:
        FileNotFoundError: If the rule file doesn't exist
    """
    try:
        with open(file_path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        print(f"{Fore.RED}Error: Rule file not found: {file_path}")
        sys.exit(1)
    except Exception as e:
        print(f"{Fore.RED}Error loading rule file: {e}")
        sys.exit(1)


def load_prompts_file(file_path: str) -> List[str]:
    """
    Load a list of prompts from a file.
    
    Args:
        file_path: Path to the prompts file
        
    Returns:
        List of prompts
        
    Raises:
        FileNotFoundError: If the prompts file doesn't exist
    """
    try:
        with open(file_path, 'r') as f:
            # Remove empty lines and strip whitespace
            prompts = [line.strip() for line in f.readlines()]
            prompts = [p for p in prompts if p and not p.startswith('#')]
            return prompts
    except FileNotFoundError:
        print(f"{Fore.RED}Error: Prompts file not found: {file_path}")
        sys.exit(1)
    except Exception as e:
        print(f"{Fore.RED}Error loading prompts file: {e}")
        sys.exit(1)


def extract_rules(content: str) -> List[str]:
    """
    Extract individual rule blocks from a file containing multiple rules.
    
    Args:
        content: String containing multiple rule definitions
        
    Returns:
        List of strings, each containing a single rule
    """
    return NovaRuleFileParser()._extract_rule_blocks_optimized(content)


def check_if_rule_needs_llm(rule) -> bool:
    """
    Check if a rule requires LLM evaluation based on its patterns and condition.
    
    Args:
        rule: The parsed Nova rule
        
    Returns:
        Boolean indicating whether LLM evaluation is needed
    """
    # Check if the rule has LLM patterns
    if hasattr(rule, 'llms') and rule.llms:
        return True
        
    # Check if the condition references LLM evaluation
    if hasattr(rule, 'condition') and rule.condition and 'llm.' in rule.condition.lower():
        return True
        
    return False


def check_if_rules_need_llm(rules) -> bool:
    """
    Check if any rule in a list requires LLM evaluation.
    
    Args:
        rules: List of parsed Nova rules
        
    Returns:
        Boolean indicating whether any rule needs LLM evaluation
    """
    for rule in rules:
        if check_if_rule_needs_llm(rule):
            return True
    
    return False


def process_prompt(rule_text: str, prompt: str, verbose: bool = False, 
                   llm_type: str = 'openai', model: Optional[str] = None,
                   llm_evaluator: Optional[Any] = None) -> Dict[str, Any]:
    """
    Process a prompt against a rule.
    
    Args:
        rule_text: Nova rule definition
        prompt: Prompt to check
        verbose: Whether to enable verbose output
        llm_type: Type of LLM evaluator to use ('openai', 'anthropic', 'azure', 'ollama', 'groq', or 'openrouter')
        model: Optional model name to use
        llm_evaluator: Optional pre-existing LLM evaluator to reuse
        
    Returns:
        Dictionary containing match results or None if processing failed
    """
    # Parse the rule
    parser = NovaParser()
    
    try:
        rule = parser.parse(rule_text)
    except Exception as e:
        print(f"{Fore.RED}Error parsing rule: {e}")
        sys.exit(1)

    return process_rule(rule, prompt, verbose, llm_type, model, llm_evaluator)


def process_rule(rule, prompt: str, verbose: bool = False,
                 llm_type: str = 'openai', model: Optional[str] = None,
                 llm_evaluator: Optional[Any] = None) -> Dict[str, Any]:
    """
    Process a prompt against an already parsed rule.

    This keeps multi-rule CLI execution on the same parsed objects used for
    fail-fast validation, avoiding divergent parsing paths.
    """
    
    # Check if this rule needs LLM evaluation
    needs_llm = check_if_rule_needs_llm(rule)
    
    # Use provided evaluator or create one if needed
    if needs_llm and not llm_evaluator:
        llm_evaluator = get_validated_evaluator(llm_type, model, verbose)
        if llm_evaluator is None:
            print(f"{Fore.RED}Error: Failed to create LLM evaluator but rule requires it.")
            sys.exit(1)
    elif not needs_llm:
        if verbose:
            print(f"{Fore.GREEN}Rule '{rule.name}' only uses keyword/semantic matching. Skipping LLM evaluator creation.")
    
    # Match the prompt against the rule
    matcher = NovaMatcher(rule, llm_evaluator=llm_evaluator)
    
    # Handle None prompts safely
    if prompt is None:
        return {
            "matched": False,
            "rule_name": rule.name,
            "meta": rule.meta,
            "matching_keywords": {},
            "matching_semantics": {},
            "matching_llm": {},
            "debug": {
                "condition": rule.condition,
                "condition_result": False,
                "all_keyword_matches": {},
                "all_semantic_matches": {},
                "all_llm_matches": {},
                "llm_info": {
                    "type": llm_type if needs_llm else "none",
                    "model": getattr(llm_evaluator, 'model', None) if needs_llm else None
                }
            }
        }
    
    # Process the prompt
    result = matcher.check_prompt(prompt)
    
    # Add LLM info to debug info
    if "debug" not in result:
        result["debug"] = {}
    
    result["debug"]["llm_info"] = {
        "type": llm_type if needs_llm else "none",
        "model": getattr(llm_evaluator, 'model', None) if needs_llm and llm_evaluator else None
    }
    
    return result


def print_rule_header(rule_number=None, total_rules=None):
    """Print a formatted header for the rule result."""
    if rule_number is not None and total_rules is not None:
        header = f" NOVA RULE CHECK [{rule_number}/{total_rules}] "
    else:
        header = " NOVA RULE CHECK "
    
    padding = "="*((70 - len(header)) // 2)
    print(f"\n{Fore.CYAN}{padding}{header}{padding}")


def print_section_header(title, char="-"):
    """Print a formatted section header."""
    print(f"\n{Fore.YELLOW}{char*70}")
    print(f"{Fore.YELLOW}{title}")
    print(f"{Fore.YELLOW}{char*70}")

def print_llm_reasons(result: Dict[str, Any]) -> None:
    """Print LLM reason fields captured by NovaMatcher."""
    debug = result.get("debug", {})
    llm_details = debug.get("all_llm_details", {})
    reasons = {
        key: details.get("reason")
        for key, details in llm_details.items()
        if isinstance(details, dict) and details.get("reason")
    }
    if not reasons:
        return

    print(f"\n{Fore.MAGENTA}LLM Reason:")
    for key, reason in reasons.items():
        print(f"  {Fore.CYAN}{key}: {Fore.WHITE}{reason}")


def print_evaluation_warnings(result: Dict[str, Any]) -> None:
    """Print fail-closed or degraded-evaluation warnings from NovaMatcher."""
    warnings = result.get("debug", {}).get("evaluation_warnings", [])
    if not warnings:
        return

    print(f"\n{Fore.YELLOW}Evaluation Warnings:")
    for warning in warnings:
        print(f"  {Fore.YELLOW}- {Fore.WHITE}{warning}")


def print_result(result: Dict[str, Any], rule_path: str, prompt: str, verbose: bool = False, 
                 rule_number=None, total_rules=None, prompt_number=None, total_prompts=None) -> None:
    """
    Print the result of a prompt check with enhanced formatting.
    
    Args:
        result: The match result
        rule_path: Path to the rule file
        prompt: The prompt that was checked
        verbose: Whether to enable verbose output
        rule_number: Current rule number (for multiple rules)
        total_rules: Total number of rules (for multiple rules)
        prompt_number: Current prompt number (for multiple prompts)
        total_prompts: Total number of prompts (for multiple prompts)
    """
    rule_name = result.get('rule_name', 'Unknown')
    meta = result.get('meta', {})
    
    print_rule_header(rule_number, total_rules)
    
    print(f"\n{Fore.WHITE}Rule File: {Fore.CYAN}{rule_path}")
    print(f"{Fore.WHITE}Rule Name: {Fore.CYAN}{rule_name}")
    
    if 'description' in meta:
        print(f"{Fore.WHITE}Description: {Fore.CYAN}{meta['description']}")
    
    if 'author' in meta:
        print(f"{Fore.WHITE}Author: {Fore.CYAN}{meta['author']}")
    
    prompt_info = ""
    if prompt_number is not None and total_prompts is not None:
        prompt_info = f" [{prompt_number}/{total_prompts}]"
    
    print(f"\n{Fore.WHITE}Prompt{prompt_info}: {Fore.YELLOW}\"{prompt}\"")
    
    match_status = f"{Back.GREEN}{Fore.BLACK} MATCHED " if result['matched'] else f"{Back.RED}{Fore.WHITE} NOT MATCHED "
    print(f"\n{Fore.WHITE}Result: {match_status}")
    print_evaluation_warnings(result)
    
    # Print match details
    if result['matched']:
        print(f"\n{Fore.CYAN}Matching Patterns:")
        
        if result['matching_keywords']:
            print(f"  {Fore.GREEN}Keywords:")
            for key in result['matching_keywords']:
                print(f"    {Fore.WHITE}• {key}")
        
        if result['matching_semantics']:
            print(f"  {Fore.GREEN}Semantics:")
            for key in result['matching_semantics']:
                print(f"    {Fore.WHITE}• {key}")
                
        if 'matching_llm' in result and result['matching_llm']:
            print(f"  {Fore.GREEN}LLM:")
            for key in result['matching_llm']:
                print(f"    {Fore.WHITE}• {key}")
    
    # Print debug information if verbose mode is enabled
    if verbose:
        print_section_header("DETAILED MATCH INFORMATION")
        
        if 'debug' in result:
            debug = result['debug']
            
            # Print LLM evaluator information
            if 'llm_info' in debug:
                llm_info = debug['llm_info']
                print(f"\n{Fore.MAGENTA}LLM Evaluator:")
                print(f"  {Fore.CYAN}Type: {Fore.WHITE}{llm_info.get('type', 'Unknown')}")
                print(f"  {Fore.CYAN}Model: {Fore.WHITE}{llm_info.get('model', 'Unknown')}")
            
            if 'condition' in debug and debug['condition']:
                print(f"\n{Fore.MAGENTA}Condition: {Fore.WHITE}{debug['condition']}")
                
            if 'all_keyword_matches' in debug:
                print(f"\n{Fore.MAGENTA}Keyword Matches:")
                for key, value in debug['all_keyword_matches'].items():
                    match_color = Fore.GREEN if value else Fore.RED
                    print(f"  {Fore.CYAN}{key}: {match_color}{value}")
            
            if 'all_semantic_matches' in debug:
                print(f"\n{Fore.MAGENTA}Semantic Matches:")
                for key, value in debug['all_semantic_matches'].items():
                    match_color = Fore.GREEN if value else Fore.RED
                    print(f"  {Fore.CYAN}{key}: {match_color}{value}")
                    
                if 'semantic_scores' in result:
                    print(f"\n{Fore.MAGENTA}Semantic Scores:")
                    for key, value in result['semantic_scores'].items():
                        # Show score in color based on threshold (assuming 0.7 is typical threshold)
                        score_color = Fore.GREEN if value >= 0.7 else Fore.YELLOW if value >= 0.5 else Fore.RED
                        print(f"  {Fore.CYAN}{key}: {score_color}{value:.4f}")
            
            if 'all_llm_matches' in debug:
                print(f"\n{Fore.MAGENTA}LLM Matches:")
                for key, value in debug['all_llm_matches'].items():
                    match_color = Fore.GREEN if value else Fore.RED
                    print(f"  {Fore.CYAN}{key}: {match_color}{value}")
                
                if 'llm_scores' in result:
                    print(f"\n{Fore.MAGENTA}LLM Confidence Scores:")
                    for key, value in result['llm_scores'].items():
                        score_color = Fore.GREEN if value >= 0.7 else Fore.YELLOW if value >= 0.5 else Fore.RED
                        print(f"  {Fore.CYAN}{key}: {score_color}{value:.4f}")

                # Print LLM reasons in verbose mode
                print_llm_reasons(result)

def print_summary(matched_count: int, total_rules: int):
    """
    Print a summary of the rule matching results.
    
    Args:
        matched_count: Number of rules that matched
        total_rules: Total number of rules checked
    """
    print_section_header("SUMMARY", "=")
    
    print(f"\n{Fore.WHITE}Total Rules Checked: {Fore.CYAN}{total_rules}")
    print(f"{Fore.WHITE}Matched Rules: {Fore.GREEN if matched_count > 0 else Fore.RED}{matched_count}")
    print(f"{Fore.WHITE}Match Rate: {Fore.CYAN}{matched_count/total_rules*100:.1f}%")
    
    # Visual match indicator
    match_bar = ""
    for i in range(total_rules):
        if i < matched_count:
            match_bar += f"{Fore.GREEN}■"
        else:
            match_bar += f"{Fore.RED}■"
    
    print(f"\n{match_bar}")


def print_prompts_summary(results: List[Dict[str, Any]], prompts: List[str]):
    """
    Print a summary of multiple prompts tested against rules.
    
    Args:
        results: List of results for each prompt
        prompts: List of prompts that were tested
    """
    print_section_header("PROMPTS SUMMARY", "=")
    
    total_prompts = len(prompts)
    matched_prompts = sum(1 for r in results if r.get('matched', False))
    
    print(f"\n{Fore.WHITE}Total Prompts Tested: {Fore.CYAN}{total_prompts}")
    print(f"{Fore.WHITE}Matched Prompts: {Fore.GREEN if matched_prompts > 0 else Fore.RED}{matched_prompts}")
    print(f"{Fore.WHITE}Match Rate: {Fore.CYAN}{matched_prompts/total_prompts*100:.1f}%")
    
    # Visual match indicator
    match_bar = ""
    for i, result in enumerate(results):
        if result.get('matched', False):
            match_bar += f"{Fore.GREEN}■"
        else:
            match_bar += f"{Fore.RED}■"
    
    print(f"\n{match_bar}\n")
    
    # Print table of prompts and their match status
    print(f"{Fore.CYAN}{'#':<4} {'Result':<10} Prompt")
    print(f"{Fore.CYAN}{'-'*70}")
    
    for i, (prompt, result) in enumerate(zip(prompts, results)):
        result_text = f"{Fore.GREEN}MATCHED" if result.get('matched', False) else f"{Fore.RED}NOT MATCHED"
        # Truncate prompt if it's too long
        display_prompt = prompt if len(prompt) < 50 else prompt[:47] + "..."
        print(f"{Fore.WHITE}{i+1:<4} {result_text:<27} {Fore.YELLOW}{display_prompt}")


def main():
    """Main entry point for the novarun tool."""
    parser = argparse.ArgumentParser(
        description="Nova Rule Runner - Check prompts against Nova rules"
    )
    
    parser.add_argument('-r', '--rule', required=True, help='Path to the Nova rule file')
    
    # Create a prompt group that requires one of the options
    prompt_group = parser.add_mutually_exclusive_group(required=True)
    prompt_group.add_argument('-p', '--prompt', help='Single prompt to check against the rule')
    prompt_group.add_argument('-f', '--file', help='Path to a file containing multiple prompts (one per line)')
    
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose output')
    parser.add_argument('-c', '--config', help='Path to Nova configuration file')
    parser.add_argument('-s', '--single', action='store_true', help='Check against only the first rule in the file (default reads all rules)')
    parser.add_argument('-l', '--llm', choices=SUPPORTED_LLM_PROVIDERS,
                       help='LLM evaluator to use (default: openai unless --config sets a provider)')
    parser.add_argument('-m', '--model', help='Specific model to use with the LLM evaluator')
    
    # Keep the -a/--all flag for backward compatibility, but make it a no-op (all rules is now default)
    parser.add_argument('-a', '--all', action='store_true', help='Check against all rules in the file (default behavior)')
    
    args = parser.parse_args()
    
    try:
        apply_config_to_args(args)
    except Exception as e:
        print(f"{Fore.RED}Error applying config file: {e}")
        sys.exit(1)

    args.llm = args.llm or 'openai'
    
    # Load the rule file
    file_content = load_rule_file(args.rule)
    
    # Determine if we're processing a single prompt or multiple prompts
    prompts = []
    if args.prompt:
        prompts = [args.prompt]
    elif args.file:
        prompts = load_prompts_file(args.file)
        if not prompts:
            print(f"{Fore.RED}No valid prompts found in {args.file}")
            sys.exit(1)
        print(f"\n{Fore.CYAN}Loaded {Fore.WHITE}{len(prompts)}{Fore.CYAN} prompts from {Fore.WHITE}{args.file}")
    
    # Check if the file contains multiple rules using the shared rule-file extractor.
    rule_blocks = extract_rules(file_content)
    if not args.single and len(rule_blocks) > 1:
        # Extract all rules from the file
        if not rule_blocks:
            print(f"{Fore.RED}No valid rules found in {args.rule}")
            sys.exit(1)
            
        print(f"\n{Fore.CYAN}Found {Fore.WHITE}{len(rule_blocks)}{Fore.CYAN} rules in {Fore.WHITE}{args.rule}")
        
        # Parse all rules first and fail closed on malformed or duplicate rules.
        try:
            parsed_rules = NovaRuleFileParser().parse_content(file_content, args.rule)
        except Exception as e:
            print(f"{Fore.RED}Error parsing rule file: {e}")
            sys.exit(1)
            
        # Check if any rule needs LLM evaluation and create a single evaluator if needed
        needs_llm = check_if_rules_need_llm(parsed_rules)
        llm_evaluator = None
        
        if needs_llm:
            if args.verbose:
                print(f"{Fore.GREEN}Creating single LLM evaluator for all rules that need it...")
            llm_evaluator = get_validated_evaluator(args.llm, args.model, args.verbose)
            if llm_evaluator is None:
                print(f"{Fore.RED}Error: Failed to create LLM evaluator but at least one rule requires it.")
                sys.exit(1)
        elif args.verbose:
            print(f"{Fore.GREEN}No rules require LLM evaluation. Skipping LLM evaluator creation.")
        
        # Process each prompt against all rules
        all_results = []
        all_matched_prompts = []
        
        for prompt_idx, prompt in enumerate(prompts):
            prompt_matched = False
            matched_count = 0
            total_rules = len(parsed_rules)
            prompt_results = []
            
            for rule_idx, rule in enumerate(parsed_rules):
                try:
                    # Use the shared LLM evaluator for all rules
                    result = process_rule(rule, prompt, args.verbose, args.llm, args.model, llm_evaluator)
                    prompt_results.append(result)
                    
                    if result['matched']:
                        matched_count += 1
                        prompt_matched = True
                        print_result(result, args.rule, prompt, args.verbose, rule_idx+1, total_rules, prompt_idx+1, len(prompts))
                except Exception as e:
                    print(f"{Fore.RED}Error processing rule #{rule_idx+1} for prompt #{prompt_idx+1}: {e}")
            
            # Add this prompt's results
            all_results.extend(prompt_results)
            if prompt_matched:
                all_matched_prompts.append(prompt_idx)
            
            # Print summary for this prompt if processing multiple rules
            if total_rules > 1:
                print_summary(matched_count, total_rules)
                
                if matched_count == 0:
                    print(f"\n{Fore.YELLOW}No rules matched prompt #{prompt_idx+1}: \"{prompt}\"")
        
        # Print summary of all prompts if processing multiple prompts
        if len(prompts) > 1:
            # Create results list mapping each prompt to its match status
            prompt_summary_results = []
            for i in range(len(prompts)):
                prompt_summary_results.append({"matched": i in all_matched_prompts})
            
            print_prompts_summary(prompt_summary_results, prompts)
        
        # Exit with success if any prompt matched any rule
        sys.exit(0 if all_matched_prompts else 1)
    else:
        # Processing a single rule with one or more prompts
        all_results = []
        all_matched = False
        
        # Parse the rule once for validation
        try:
            parser = NovaParser()
            single_rule = parser.parse(file_content)
        except Exception as e:
            print(f"{Fore.RED}Error parsing rule: {e}")
            sys.exit(1)
            
        # Create LLM evaluator if needed for this rule
        needs_llm = check_if_rule_needs_llm(single_rule)
        llm_evaluator = None
        
        if needs_llm:
            if args.verbose:
                print(f"{Fore.GREEN}Creating LLM evaluator for rule '{single_rule.name}'...")
            llm_evaluator = get_validated_evaluator(args.llm, args.model, args.verbose)
            if llm_evaluator is None:
                print(f"{Fore.RED}Error: Failed to create LLM evaluator but rule requires it.")
                sys.exit(1)
        elif args.verbose:
            print(f"{Fore.GREEN}Rule '{single_rule.name}' doesn't require LLM evaluation. Skipping LLM evaluator creation.")
        
        for prompt_idx, prompt in enumerate(prompts):
            result = process_prompt(file_content, prompt, args.verbose, args.llm, args.model, llm_evaluator)
            all_results.append(result)
            
            if result['matched']:
                all_matched = True
            
            # Print result with prompt number if we have multiple prompts
            if len(prompts) > 1:
                print_result(result, args.rule, prompt, args.verbose, 
                            prompt_number=prompt_idx+1, total_prompts=len(prompts))
            else:
                print_result(result, args.rule, prompt, args.verbose)
        
        # Print summary if processing multiple prompts
        if len(prompts) > 1:
            print_prompts_summary(all_results, prompts)
        
        # Return exit code based on match result
        sys.exit(0 if all_matched else 1)


if __name__ == "__main__":
    main()
