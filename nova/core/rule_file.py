"""
NOVA: The Prompt Pattern Matching
Author: Thomas Roccia
twitter: @fr0gger_
License: MIT License
Version: see nova._version
Description: Multi-rule .nov file parser
"""

from typing import List, Set

from nova.core.rules import NovaRule
from nova.core.parser import NovaParser, NovaParserError, RULE_START_PATTERN


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
            # We use a faster, single-pass algorithm that tracks quote state
            # to avoid counting braces inside quoted strings
            brace_count = 0
            rule_end_pos = -1
            in_quotes = False
            escape_next = False

            for pos, char in enumerate(rule_text):
                if escape_next:
                    # Previous char was backslash, skip this char
                    escape_next = False
                    continue

                if char == '\\':
                    # Next char is escaped
                    escape_next = True
                    continue

                if char == '"':
                    # Toggle quote state
                    in_quotes = not in_quotes
                    continue

                # Only count braces when not inside quotes
                if not in_quotes:
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
