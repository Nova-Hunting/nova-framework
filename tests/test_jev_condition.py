import pytest
from nova.core.parser import NovaParser
from nova.core.jev import Predicate
from nova.evaluators.jev.condition import compile_condition
from test_jev_parser import source

T, F, U = Predicate.TRUE, Predicate.FALSE, Predicate.UNKNOWN


@pytest.mark.parametrize("condition,values,expected", [
    ("not jev.$scope", {}, U),
    ("jev.$scope or jev.$risk", {"jev.$scope": T}, T),
    ("jev.$scope and jev.$risk", {"jev.$scope": F}, F),
    ("jev.$scope and jev.$risk", {"jev.$scope": T}, U),
    ("jev.$scope or jev.$risk", {"jev.$scope": F}, U),
    ("2 of jev", {"jev.$scope": T, "jev.$risk": T}, T),
    ("2 of jev", {"jev.$scope": F, "jev.$risk": F}, F),
    ("2 of jev", {"jev.$scope": T}, U),
    ("all of jev", {"jev.$scope": F}, F),
    ("jev.*", {}, U),
    ("all of ($s*)", {"jev.$scope": T}, T),
    ("jev.$s*", {"jev.$scope": T}, T),
])
def test_partial_truth(condition, values, expected):
    node = compile_condition(NovaParser().parse(source(condition)))
    assert node.evaluate(values) is expected


def test_prunes_irrelevant_subexpression():
    node = compile_condition(NovaParser().parse(source("(jev.$scope and jev.$risk) or jev.$operation")))
    assert node.needed({"jev.$scope": F}) == {"jev.$operation"}


def test_predicates_cannot_coerce_uncertainty_to_false():
    with pytest.raises(TypeError):
        bool(U)
