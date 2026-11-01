"""The uncertain values of a case, as the studies read them."""

import pytest

import gemini as gm
from gemini.study._utils.uncertain import declared
from tests.fixtures.errors import raises
from tests.unit.study.conftest import shallow_case

PATH = "assumptions.finance.opex.electricity"


def test_declared_lists_each_value_with_its_case_name_and_si_value():
    """The name carries the case prefix and the value is the one of the case."""
    case = shallow_case(uncertain={PATH: {"kind": "uniform", "min": 100, "max": 140}})
    [(name, uncertainty, value)] = declared(case, "sample")
    assert name == f"case.{PATH}" and uncertainty.kind == "uniform"
    assert value == pytest.approx(120 / 3.6e9)


def test_declared_refuses_a_case_without_uncertainty():
    """The error names the study."""
    with raises(gm.errors.ValidationError, "missing_value", match="study.sensitivity"):
        declared(shallow_case(), "sensitivity")
