import pytest
from nova.core.parser import NovaParser
from nova.core.decision import Predicate
from nova.evaluators.decision.condition import compile_condition
from test_decision_parser import source

T, F, U = Predicate.TRUE, Predicate.FALSE, Predicate.UNKNOWN


@pytest.mark.parametrize("condition,values,expected", [
    ("not llm.$scope", {}, U),
    ("llm.$scope or llm.$risk", {"llm.$scope": T}, T),
    ("llm.$scope and llm.$risk", {"llm.$scope": F}, F),
    ("llm.$scope and llm.$risk", {"llm.$scope": T}, U),
    ("llm.$scope or llm.$risk", {"llm.$scope": F}, U),
    ("2 of llm", {"llm.$scope": T, "llm.$risk": T}, T),
    ("2 of llm", {"llm.$scope": F, "llm.$risk": F}, F),
    ("2 of llm", {"llm.$scope": T}, U),
    ("all of llm", {"llm.$scope": F}, F),
    ("llm.*", {}, U),
    ("all of ($s*)", {"llm.$scope": T}, T),
    ("llm.$s*", {"llm.$scope": T}, T),
])
def test_partial_truth(condition, values, expected):
    node = compile_condition(NovaParser().parse(source(condition)))
    assert node.evaluate(values) is expected


def test_prunes_irrelevant_subexpression():
    node = compile_condition(NovaParser().parse(source("(llm.$scope and llm.$risk) or llm.$operation")))
    assert node.needed({"llm.$scope": F}) == {"llm.$operation"}


def test_predicates_cannot_coerce_uncertainty_to_false():
    with pytest.raises(TypeError):
        bool(U)
