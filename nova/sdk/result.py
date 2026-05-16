"""
Nova SDK Result Classes

Rich result objects for Nova SDK scanning.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from .policy import Action


@dataclass
class RuleMatch:
    """Details about a single matched rule."""
    rule_name: str
    meta: Dict[str, str]
    action: Action
    severity: Optional[str]
    source_file: Optional[str] = None  # Source .nov file path
    matching_keywords: Dict[str, bool] = field(default_factory=dict)
    matching_semantics: Dict[str, bool] = field(default_factory=dict)
    matching_llm: Dict[str, bool] = field(default_factory=dict)
    semantic_scores: Dict[str, float] = field(default_factory=dict)
    llm_scores: Dict[str, float] = field(default_factory=dict)
    matched_patterns: List[str] = field(default_factory=list)


@dataclass
class ScanResult:
    """
    Rich result object from Nova SDK scanning.

    Provides convenient boolean properties and access to detailed match info.

    Attributes:
        original_text: The original unmodified text
        sanitized_text: Text with redactions applied
        matches: List of all RuleMatch objects
        redactions: List of redaction details

    Properties:
        blocked: True if any match resulted in BLOCK action
        flagged: True if any match resulted in FLAG action
        redacted: True if any content was redacted
        allowed: True if no blocking actions were triggered
        clean: True if no rules matched at all
    """
    original_text: str
    sanitized_text: str
    matches: List[RuleMatch] = field(default_factory=list)
    actions_taken: Dict[str, Action] = field(default_factory=dict)
    redactions: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    rule_warnings: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        """Returns True if any rule triggered a BLOCK action."""
        return any(m.action == Action.BLOCK for m in self.matches)

    @property
    def flagged(self) -> bool:
        """Returns True if any rule triggered a FLAG action."""
        return any(m.action == Action.FLAG for m in self.matches)

    @property
    def redacted(self) -> bool:
        """Returns True if any content was redacted."""
        return len(self.redactions) > 0

    @property
    def allowed(self) -> bool:
        """Returns True if no blocking actions were triggered."""
        return not self.blocked

    @property
    def clean(self) -> bool:
        """Returns True if no rules matched at all."""
        return len(self.matches) == 0

    @property
    def highest_severity(self) -> Optional[str]:
        """Returns the highest severity level from all matches."""
        severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        max_severity = None
        max_score = 0

        for match in self.matches:
            sev = (match.severity or match.meta.get("severity", "")).lower()
            if sev in severity_order and severity_order[sev] > max_score:
                max_score = severity_order[sev]
                max_severity = sev

        return max_severity

    @property
    def match_count(self) -> int:
        """Returns the number of matched rules."""
        return len(self.matches)

    @property
    def has_warnings(self) -> bool:
        """Returns True if any rule produced scan warnings."""
        return len(self.warnings) > 0

    @property
    def blocked_rules(self) -> List[str]:
        """Returns list of rule names that triggered BLOCK action."""
        return [m.rule_name for m in self.matches if m.action == Action.BLOCK]

    @property
    def flagged_rules(self) -> List[str]:
        """Returns list of rule names that triggered FLAG action."""
        return [m.rule_name for m in self.matches if m.action == Action.FLAG]

    def get_matches_by_action(self, action: Action) -> List[RuleMatch]:
        """Get all matches that resulted in a specific action."""
        return [m for m in self.matches if m.action == action]

    def get_matches_by_category(self, category_prefix: str) -> List[RuleMatch]:
        """Get all matches in a category (e.g., 'jailbreak')."""
        return [
            m for m in self.matches
            if m.meta.get("category", "").startswith(category_prefix)
        ]

    def get_matches_by_severity(self, severity: str) -> List[RuleMatch]:
        """Get all matches with a specific severity."""
        severity_lower = severity.lower()
        return [
            m for m in self.matches
            if (m.severity or m.meta.get("severity", "")).lower() == severity_lower
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for serialization."""
        return {
            "blocked": self.blocked,
            "flagged": self.flagged,
            "redacted": self.redacted,
            "allowed": self.allowed,
            "clean": self.clean,
            "sanitized_text": self.sanitized_text,
            "original_text": self.original_text,
            "highest_severity": self.highest_severity,
            "match_count": self.match_count,
            "blocked_rules": self.blocked_rules,
            "flagged_rules": self.flagged_rules,
            "warnings": self.warnings,
            "rule_warnings": self.rule_warnings,
            "matches": [
                {
                    "rule_name": m.rule_name,
                    "meta": m.meta,
                    "action": m.action.value,
                    "severity": m.severity,
                    "source_file": m.source_file,
                    "matching_keywords": m.matching_keywords,
                    "matching_semantics": m.matching_semantics,
                    "matching_llm": m.matching_llm,
                    "semantic_scores": m.semantic_scores,
                    "llm_scores": m.llm_scores,
                    "matched_patterns": m.matched_patterns,
                }
                for m in self.matches
            ],
            "redactions": self.redactions
        }

    def __bool__(self) -> bool:
        """Returns True if any rules matched."""
        return len(self.matches) > 0

    def print_debug(self) -> None:
        """
        Print detailed match information for debugging.

        Useful for troubleshooting false positives or understanding
        which patterns triggered matches.
        """
        print("\n[NOVA DEBUG] Scan Result Summary")
        print(f"[NOVA DEBUG] Matches: {self.match_count}")
        print(f"[NOVA DEBUG] Blocked: {self.blocked}")
        print(f"[NOVA DEBUG] Flagged: {self.flagged}")
        print(f"[NOVA DEBUG] Redacted: {self.redacted}")
        print(f"[NOVA DEBUG] Highest Severity: {self.highest_severity or 'N/A'}")
        if self.warnings:
            print(f"[NOVA DEBUG] Warnings: {len(self.warnings)}")
            for warning in self.warnings:
                print(f"  - {warning}")

        if not self.matches:
            print("[NOVA DEBUG] No matches - input is clean")
            return

        for i, match in enumerate(self.matches, 1):
            print(f"\nMatch {i}: {match.rule_name}")
            if match.source_file:
                print(f"  Source: {match.source_file}")
            print(f"  Action: {match.action.value.upper()}")
            print(f"  Severity: {match.severity or 'N/A'}")
            print(f"  Category: {match.meta.get('category', 'N/A')}")

            # Keywords
            if match.matching_keywords:
                matched_kw = [k for k, v in match.matching_keywords.items() if v]
                print(f"  Keywords matched: {matched_kw if matched_kw else 'None'}")
            else:
                print("  Keywords matched: None")

            # Semantics with scores
            if match.matching_semantics or match.semantic_scores:
                print("  Semantics matched:")
                for name in set(list(match.matching_semantics.keys()) + list(match.semantic_scores.keys())):
                    matched = match.matching_semantics.get(name, False)
                    score = match.semantic_scores.get(name, 0)
                    status = "← MATCH" if matched else ""
                    print(f"    - {name}: score={score:.3f} {status}")
            else:
                print("  Semantics matched: None")

            # LLM
            if match.matching_llm or match.llm_scores:
                print("  LLM matched:")
                for name in set(list(match.matching_llm.keys()) + list(match.llm_scores.keys())):
                    matched = match.matching_llm.get(name, False)
                    score = match.llm_scores.get(name, 0)
                    status = "← MATCH" if matched else ""
                    print(f"    - {name}: score={score:.3f} {status}")
            else:
                print("  LLM matched: None")

        print()  # Final newline for readability
