import pytest
from nova.core.parser import NovaParser
from nova.core.sys1 import Predicate
from nova.evaluators.sys1.condition import compile_condition
from test_sys1_parser import source

T, F, U = Predicate.TRUE, Predicate.FALSE, Predicate.UNKNOWN


@pytest.mark.parametrize("condition,values,expected", [
    ("not sys1.$scope", {}, U),
    ("sys1.$scope or sys1.$risk", {"sys1.$scope": T}, T),
    ("sys1.$scope and sys1.$risk", {"sys1.$scope": F}, F),
    ("sys1.$scope and sys1.$risk", {"sys1.$scope": T}, U),
    ("sys1.$scope or sys1.$risk", {"sys1.$scope": F}, U),
    ("2 of sys1", {"sys1.$scope": T, "sys1.$risk": T}, T),
    ("2 of sys1", {"sys1.$scope": F, "sys1.$risk": F}, F),
    ("2 of sys1", {"sys1.$scope": T}, U),
    ("all of sys1", {"sys1.$scope": F}, F),
    ("sys1.*", {}, U),
    ("all of ($s*)", {"sys1.$scope": T}, T),
    ("sys1.$s*", {"sys1.$scope": T}, T),
])
def test_partial_truth(condition, values, expected):
    node = compile_condition(NovaParser().parse(source(condition)))
    assert node.evaluate(values) is expected


def test_prunes_irrelevant_subexpression():
    node = compile_condition(NovaParser().parse(source("(sys1.$scope and sys1.$risk) or sys1.$operation")))
    assert node.needed({"sys1.$scope": F}) == {"sys1.$operation"}


def test_predicates_cannot_coerce_uncertainty_to_false():
    with pytest.raises(TypeError):
        bool(U)
