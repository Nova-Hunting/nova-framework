from nova.core.matcher import NovaMatcher
from nova.core.parser import NovaParser, NovaParserError, NovaRuleFileParser
from nova.evaluators.condition import (
    can_llm_change_outcome,
    can_semantics_change_outcome,
    evaluate_condition,
)


def test_section_all_quantifier_requires_every_match():
    assert evaluate_condition(
        "all of keywords.*",
        {"$one": True, "$two": True},
        {},
        {},
    ) is True
    assert evaluate_condition(
        "all of keywords.*",
        {"$one": True, "$two": False},
        {},
        {},
    ) is False


def test_prefix_quantifiers_across_sections():
    assert evaluate_condition(
        "all of ($abuse*)",
        {"$abuse_keyword": True},
        {"$abuse_semantic": True},
        {"$abuse_llm": True},
    ) is True
    assert evaluate_condition(
        "all of ($abuse*)",
        {"$abuse_keyword": True},
        {"$abuse_semantic": False},
        {},
    ) is False
    assert evaluate_condition(
        "2 of ($abuse*)",
        {"$abuse_keyword": True},
        {"$abuse_semantic": False},
        {"$abuse_llm": True},
    ) is True


def test_section_prefix_quantifier_counts_only_matching_section_prefix():
    assert evaluate_condition(
        "2 of keywords.$abuse*",
        {"$abuse_one": True, "$abuse_two": True, "$other": False},
        {"$abuse_semantic": True},
        {},
    ) is True
    assert evaluate_condition(
        "2 of keywords.$abuse*",
        {"$abuse_one": True, "$abuse_two": False},
        {"$abuse_semantic": True},
        {},
    ) is False


def test_condition_variables_do_not_replace_name_prefixes():
    keyword_matches = {"$a": False, "$aa": True}

    assert evaluate_condition("keywords.$aa", keyword_matches, {}, {}) is True
    assert evaluate_condition("keywords.$a or keywords.$aa", keyword_matches, {}, {}) is True
    assert evaluate_condition("$a or $aa", keyword_matches, {}, {}) is True
    assert evaluate_condition("$a and $aa", keyword_matches, {}, {}) is False
    assert evaluate_condition("$aa*", keyword_matches, {}, {}) is False


def test_parser_accepts_quantified_prefix_wildcards():
    rule = NovaParser().parse(
        """
rule PrefixWildcardRule
{
    keywords:
        $abuse_one = "alpha"
        $abuse_two = "beta"

    condition:
        all of ($abuse*)
}
"""
    )

    assert rule.condition == "all of ($abuse*)"

    rule = NovaParser().parse(
        """
rule PrefixWildcardRule
{
    keywords:
        $abuse_one = "alpha"
        $abuse_two = "beta"

    condition:
        2 of ($abuse*)
}
"""
    )

    assert rule.condition == "2 of ($abuse*)"


def test_parser_skips_leading_comments_before_rule_declaration():
    rule = NovaParser().parse(
        """
// Copyright header
# Rule pack note

rule HeaderCommentRule
{
    keywords:
        $hit = "alpha"

    condition:
        keywords.$hit
}
"""
    )

    assert rule.name == "HeaderCommentRule"
    assert "$hit" in rule.keywords


def test_parser_skips_hash_comments_inside_rule_sections():
    rule = NovaParser().parse(
        """
rule SectionCommentRule
{
    meta:
        # Metadata note
        description = "comment-compatible rule"

    keywords:
        # Keyword note
        $hit = "alpha"

    semantics:
        # Semantic note
        $topic = "risky topic" (0.7)

    llm:
        # LLM note
        $judge = "Decide whether this is risky" (0.4)

    condition:
        # Condition note
        keywords.$hit or semantics.$topic or llm.$judge
}
"""
    )

    assert rule.meta["description"] == "comment-compatible rule"
    assert "$hit" in rule.keywords
    assert "$topic" in rule.semantics
    assert "$judge" in rule.llms
    assert rule.condition == "keywords.$hit or semantics.$topic or llm.$judge"


def test_parser_rejects_unknown_sections():
    try:
        NovaParser().parse(
            """
rule UnknownSectionRule
{
    keyword:
        $hit = "alpha"

    condition:
        keywords.$hit
}
"""
        )
    except NovaParserError as exc:
        assert "Unknown section 'keyword'" in str(exc)
        assert "keywords" in str(exc)
    else:
        raise AssertionError("parser accepted unknown rule section")


def test_rule_file_parser_ignores_rule_words_inside_metadata_values():
    rules = NovaRuleFileParser().parse_content(
        """
rule FirstRule
{
    meta:
        description = "documents the word rule without declaring one"

    keywords:
        $first = "alpha"

    condition:
        keywords.$first
}

rule SecondRule
{
    keywords:
        $second = "beta"

    condition:
        keywords.$second
}
""",
        source_name="inline rules",
    )

    assert [rule.name for rule in rules] == ["FirstRule", "SecondRule"]


def test_parser_rejects_unmatched_quantified_prefix_wildcards():
    try:
        NovaParser().parse(
            """
rule PrefixWildcardRule
{
    keywords:
        $abuse_one = "alpha"

    condition:
        all of ($missing*)
}
"""
        )
    except NovaParserError as exc:
        assert "$missing*" in str(exc)
    else:
        raise AssertionError("parser accepted unmatched quantified prefix wildcard")


def test_parser_rejects_raw_standalone_wildcard():
    try:
        NovaParser().parse(
            """
rule RawStandaloneWildcardRule
{
    keywords:
        $ris = "alpha"
        $risk_one = "beta"

    condition:
        $risk*
}
"""
        )
    except NovaParserError as exc:
        assert "Invalid standalone wildcard syntax" in str(exc)
    else:
        raise AssertionError("parser accepted raw standalone wildcard")


def test_matcher_does_not_treat_prefix_wildcard_as_shorter_variable():
    rule = NovaParser().parse(
        """
rule PrefixWildcardShortNameRule
{
    keywords:
        $ris = "alpha"
        $risk_one = "beta"

    condition:
        keywords.$risk*
}
"""
    )

    matcher = NovaMatcher(rule)
    result = matcher.check_prompt("alpha")

    assert result["matched"] is False
    assert result["debug"]["all_keyword_matches"] == {"$risk_one": False}


def test_parser_rejects_malformed_variable_names():
    bad_rules = [
        """
rule BadKeywordName
{
    keywords:
        $bad-name = "alpha"

    condition:
        keywords.*
}
""",
        """
rule BadSemanticName
{
    semantics:
        $bad.name = "alpha"

    condition:
        semantics.*
}
""",
        """
rule BadLlmName
{
    llm:
        $ = "Decide whether this is risky"

    condition:
        llm.*
}
""",
    ]

    for rule_text in bad_rules:
        try:
            NovaParser().parse(rule_text)
        except NovaParserError as exc:
            assert "Variable names" in str(exc)
        else:
            raise AssertionError("parser accepted malformed variable name")


def test_parser_rejects_duplicate_variable_names_across_sections():
    try:
        NovaParser().parse(
            """
rule DuplicateCrossSectionVariableRule
{
    keywords:
        $risk = "alpha"

    llm:
        $risk = "Decide whether this is risky"

    condition:
        keywords.$risk or llm.$risk
}
"""
        )
    except NovaParserError as exc:
        assert "Duplicate variable name across sections" in str(exc)
        assert "$risk" in str(exc)
    else:
        raise AssertionError("parser accepted duplicate cross-section variable name")


def test_matcher_honors_all_of_section_wildcard():
    rule = NovaParser().parse(
        """
rule AllKeywordsRule
{
    keywords:
        $one = "alpha"
        $two = "beta"

    condition:
        all of keywords.*
}
"""
    )
    matcher = NovaMatcher(rule)

    assert matcher.check_prompt("alpha beta")["matched"] is True


def test_matcher_honors_bare_section_quantifiers():
    parser = NovaParser()
    rule = parser.parse(
        """
rule BareKeywordQuantifierRule
{
    keywords:
        $one = "alpha"
        $two = "beta"

    condition:
        2 of keywords
}
"""
    )

    matcher = NovaMatcher(rule)
    matched = matcher.check_prompt("alpha beta")
    non_matched = matcher.check_prompt("alpha")

    assert matched["matched"] is True
    assert matched["debug"]["all_keyword_matches"] == {"$one": True, "$two": True}
    assert non_matched["matched"] is False
    assert non_matched["debug"]["all_keyword_matches"] == {"$one": True, "$two": False}

    any_rule = parser.parse(
        """
rule BareAnyKeywordQuantifierRule
{
    keywords:
        $one = "alpha"
        $two = "beta"

    condition:
        any of keywords
}
"""
    )

    assert NovaMatcher(any_rule).check_prompt("alpha")["matched"] is True
    assert matcher.check_prompt("alpha only")["matched"] is False


def test_matcher_evaluates_bare_semantic_quantifiers():
    class FakeSemanticEvaluator:
        def evaluate(self, pattern, text):
            matched = pattern.pattern in text
            return matched, 1.0 if matched else 0.0

    parser = NovaParser()
    rule = parser.parse(
        """
rule BareSemanticQuantifierRule
{
    semantics:
        $one = "alpha" (0.7)
        $two = "beta" (0.7)

    condition:
        any of semantics
}
"""
    )

    result = NovaMatcher(rule, semantic_evaluator=FakeSemanticEvaluator()).check_prompt("alpha")

    assert result["matched"] is True
    assert result["debug"]["all_semantic_matches"] == {"$one": True, "$two": False}

    all_rule = parser.parse(
        """
rule BareAllSemanticQuantifierRule
{
    semantics:
        $one = "alpha" (0.7)
        $two = "beta" (0.7)

    condition:
        all of semantics
}
"""
    )

    all_result = NovaMatcher(all_rule, semantic_evaluator=FakeSemanticEvaluator()).check_prompt("alpha beta")

    assert all_result["matched"] is True
    assert all_result["debug"]["all_semantic_matches"] == {"$one": True, "$two": True}


def test_matcher_evaluates_bare_llm_quantifiers():
    class FakeLLMEvaluator:
        def evaluate_prompt(self, prompt_template, text, temperature=0.1):
            matched = prompt_template in text
            return matched, 1.0 if matched else 0.0, {"reason": "fake"}

    parser = NovaParser()
    rule = parser.parse(
        """
rule BareLlmQuantifierRule
{
    llm:
        $one = "alpha" (0.1)
        $two = "beta" (0.1)

    condition:
        any of llm
}
"""
    )

    result = NovaMatcher(rule, llm_evaluator=FakeLLMEvaluator()).check_prompt("alpha")

    assert result["matched"] is True
    assert result["debug"]["all_llm_matches"] == {"$one": True, "$two": False}

    all_rule = parser.parse(
        """
rule BareAllLlmQuantifierRule
{
    llm:
        $one = "alpha" (0.1)
        $two = "beta" (0.1)

    condition:
        all of llm
}
"""
    )

    all_result = NovaMatcher(all_rule, llm_evaluator=FakeLLMEvaluator()).check_prompt("alpha beta")

    assert all_result["matched"] is True
    assert all_result["debug"]["all_llm_matches"] == {"$one": True, "$two": True}


def test_matcher_does_not_short_circuit_cross_stage_all_prefix():
    class RejectingLLM:
        def evaluate_prompt(self, pattern, text, temperature=0.1):
            return False, 0.0, {"reason": "forced non-match"}

    rule = NovaParser().parse(
        """
rule CrossStageAllRule
{
    keywords:
        $risk_keyword = "alpha"

    llm:
        $risk_llm = "Decide whether the prompt is risky"

    condition:
        all of ($risk*)
}
"""
    )
    matcher = NovaMatcher(rule, llm_evaluator=RejectingLLM())

    result = matcher.check_prompt("alpha")

    assert result["matched"] is False
    assert result["debug"]["all_llm_matches"] == {"$risk_llm": False}


def test_matcher_fails_closed_when_required_llm_is_unavailable():
    rule = NovaParser().parse(
        """
rule NegatedLlmRule
{
    llm:
        $safe = "Decide whether the prompt is safe"

    condition:
        not llm.$safe
}
"""
    )
    matcher = NovaMatcher(rule, create_llm_evaluator=False)

    result = matcher.check_prompt("alpha")

    assert result["matched"] is False
    assert "requires LLM evaluation" in result["debug"]["evaluation_warnings"][0]


def test_matcher_fails_closed_when_semantic_evaluator_errors():
    class ErrorSemanticEvaluator:
        def __init__(self):
            self.last_error = None

        def evaluate(self, pattern, text):
            self.last_error = "semantic model unavailable"
            return False, 0.0

    rule = NovaParser().parse(
        """
rule NegatedSemanticErrorRule
{
    semantics:
        $safe = "safe content" (0.7)

    condition:
        not semantics.$safe
}
"""
    )
    matcher = NovaMatcher(rule, semantic_evaluator=ErrorSemanticEvaluator())

    result = matcher.check_prompt("alpha")

    assert result["matched"] is False
    assert "semantics.$safe evaluation errored" in result["debug"]["evaluation_warnings"][0]


def test_matcher_fails_closed_when_llm_evaluator_returns_error_details():
    class ErrorLLMEvaluator:
        def evaluate_prompt(self, pattern, text, temperature=0.1):
            return False, 0.0, {"error": "provider unavailable"}

    rule = NovaParser().parse(
        """
rule NegatedLlmErrorRule
{
    llm:
        $safe = "Decide whether the prompt is safe"

    condition:
        not llm.$safe
}
"""
    )
    matcher = NovaMatcher(rule, llm_evaluator=ErrorLLMEvaluator())

    result = matcher.check_prompt("alpha")

    assert result["matched"] is False
    assert "llm.$safe evaluation errored" in result["debug"]["evaluation_warnings"][0]
    assert result["debug"]["all_llm_details"]["$safe"]["error"] == "provider unavailable"


def test_matcher_skip_llm_fails_closed_when_llm_can_change_outcome():
    class MatchingLLM:
        def evaluate_prompt(self, pattern, text, temperature=0.1):
            return True, 0.9, {"reason": "safe"}

    rule = NovaParser().parse(
        """
rule SkipNegatedLlmRule
{
    llm:
        $safe = "Decide whether the prompt is safe"

    condition:
        not llm.$safe
}
"""
    )
    matcher = NovaMatcher(rule, llm_evaluator=MatchingLLM())

    skipped = matcher.check_prompt("alpha", skip_llm=True)
    full = matcher.check_prompt("alpha")

    assert skipped["matched"] is False
    assert "skipped LLM evaluation" in skipped["debug"]["evaluation_warnings"][0]
    assert skipped["debug"]["all_llm_matches"] == {}
    assert full["matched"] is False
    assert full["debug"]["all_llm_matches"] == {"$safe": True}


def test_matcher_can_skip_unavailable_llm_when_condition_is_already_decided():
    rule = NovaParser().parse(
        """
rule KeywordOrLlmRule
{
    keywords:
        $hit = "alpha"

    llm:
        $judge = "Decide whether the prompt is risky"

    condition:
        keywords.$hit or llm.$judge
}
"""
    )
    matcher = NovaMatcher(rule, create_llm_evaluator=False)

    result = matcher.check_prompt("alpha")

    assert result["matched"] is True
    assert result["debug"]["evaluation_warnings"] == []


def test_condition_change_helpers_handle_quantified_wildcards():
    assert can_semantics_change_outcome("all of semantics.*", {}) is True
    assert can_semantics_change_outcome("any of semantics", {}) is True
    assert can_semantics_change_outcome("all of semantics", {}) is True
    assert can_llm_change_outcome("2 of ($risk*)", {"$risk_keyword": True}, {}) is True
    assert can_llm_change_outcome("any of llm", {}, {}) is True
    assert can_llm_change_outcome("all of llm", {}, {}) is True
    assert can_llm_change_outcome("keywords.$hit or all of llm.*", {"$hit": True}, {}) is False
