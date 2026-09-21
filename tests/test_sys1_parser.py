import pytest

from nova.core.parser import NovaParser, NovaParserError
from nova.core.rule_file import NovaRuleFileParser
from nova.core.sys1 import NoulPattern, ChoicePattern, ScorePattern


DECLARATIONS = '''
    $scope = noul "Outside approved scope? {literal}" {
        true = "Outside"
        false = "Within"
        threshold = 0.7
    }
    $operation = choice "Primary operation?" {
        options = {
            read = "Read a file at https://example.com"
            write = "Write a file"
        }
        match = ["write",]
        min_confidence = 0.6
    }
    $risk = score "Potential impact?" {
        levels = [
            "None", "Limited", "Serious",
        ]
        threshold = 1.5
        min_confidence = 0.6
    }
'''


def source(condition="any of sys1", declarations=DECLARATIONS, extra="", name="Risk"):
    return f"rule {name} {{\n{extra}\nsys1:\n{declarations}\ncondition:\n{condition}\n}}"


def test_mixed_nested_file_and_regex_literals():
    text = source(extra='keywords:\n$secret = /[{}]a{1,3}\\/x/i\n')
    text += '\n# closing braces } do not count\nrule Legacy {\nkeywords:\n$x = "x"\ncondition:\n$x\n}'
    rules = NovaRuleFileParser().parse_content(text)
    assert len(rules) == 2
    assert isinstance(rules[0].sys1['$scope'], NoulPattern)
    assert isinstance(rules[0].sys1['$operation'], ChoicePattern)
    assert isinstance(rules[0].sys1['$risk'], ScorePattern)
    assert rules[0].sys1['$risk'].threshold == 1.5


@pytest.mark.parametrize("old,new", [
    ('noul "', 'unknown "'), ('threshold = 0.7', 'threshold = nan'),
    ('threshold = 0.7', 'threshold = 1.1'), ('threshold = 1.5', 'threshold = 3'),
    ('threshold = 0.7', 'min_confidence = 0.7'),
    ('threshold = 0.7', 'threshold = 0.7\nthreshold = 0.8'),
    ('false = "Within"', ''), ('match = ["write",]', 'match = ["undefined"]'),
    ('match = ["write",]', 'match = []'), ('"None", "Limited", "Serious",', '"None",'),
    ('read = "Read', 'write = "Read'), ('"Primary operation?"', '""'),
    ('min_confidence = 0.6', 'confidence = 0.6'),
    ('"None", "Limited"', '"None" "Limited"'),
    ('$operation =', '$scope ='),
])
def test_invalid_declarations(old, new):
    with pytest.raises(NovaParserError):
        NovaParser().parse(source(declarations=DECLARATIONS.replace(old, new)))


@pytest.mark.parametrize("condition", ["sys1.$missing", "sys1.$risk.score >= 2", "not", "sys1.$scope sys1.$risk", "4 of sys1"])
def test_invalid_conditions(condition):
    with pytest.raises(NovaParserError):
        NovaParser().parse(source(condition))


def test_trailing_content_unclosed_and_duplicate_sections():
    for text in [source() + "junk", source()[:-2], source(extra="sys1:\n")]:
        with pytest.raises(NovaParserError):
            NovaParser().parse(text)


def test_qualified_duplicate_names_allowed_but_ambiguous_bare_reference_rejected():
    extra = 'keywords:\n$scope = "scope"\n'
    NovaParser().parse(source("keywords.$scope or sys1.$scope", extra=extra))
    with pytest.raises(NovaParserError, match="Ambiguous"):
        NovaParser().parse(source("$scope", extra=extra))


def test_legacy_unquoted_metadata_and_new_escaped_questions():
    legacy = '''rule Legacy {
meta:
description = Explanation: ordinary text
author = O'Reilly
url = https://example.com
keywords:
$x = "x"
condition:
$x
}'''
    parsed = NovaParser().parse(legacy)
    assert parsed.meta["description"] == "Explanation: ordinary text"
    assert parsed.meta["author"] == "O'Reilly"
    assert parsed.meta["url"] == "https://example.com"
    question = DECLARATIONS.replace('Outside approved scope? {literal}', r'Is "quoted" text outside scope?'.replace('"', r'\"'))
    parsed = NovaParser().parse(source(declarations=question))
    assert '"quoted"' in parsed.sys1["$scope"].instructions


@pytest.mark.parametrize("condition", ["sys1", "$s*"])
def test_no_section_or_wildcard_shorthand(condition):
    with pytest.raises(NovaParserError):
        NovaParser().parse(source(condition))


def test_old_section_reports_migration_instead_of_evaluating_it():
    old = source().replace("sys1:", "jev:").replace("of sys1", "of jev")
    with pytest.raises(NovaParserError, match="renamed to 'sys1:'"):
        NovaParser().parse(old)
