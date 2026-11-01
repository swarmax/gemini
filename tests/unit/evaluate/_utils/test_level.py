"""A price of the case as the run reads it."""

import numpy as np
import pytest

import gemini as gm
from gemini.evaluate._utils.level import level
from gemini.units import Quantity
from tests.fixtures.cases import make_case
from tests.fixtures.errors import raises

PATH = "assumptions.finance.opex.electricity"


def priced(value, count=4):
    """Return a case of ``count`` steps whose electricity costs ``value``."""
    return make_case(count=count, finance={"opex": gm.case.Opex(electricity=value)})


def test_a_constant_is_a_float():
    """100 per MWh is a number of currency per joule."""
    assert level(priced(Quantity(100, "EUR/MWh")), PATH, 4) == pytest.approx(100 / 3.6e9)


def test_a_profile_is_an_array_with_one_value_per_step():
    """The values are kept in order."""
    found = level(priced(Quantity([1.0, 2.0, 3.0, 4.0], "currency/J")), PATH, 4)
    assert isinstance(found, np.ndarray) and list(found) == [1.0, 2.0, 3.0, 4.0]


def test_a_profile_of_another_length_than_the_run_is_invalid_value():
    """The error names the path."""
    case = priced(Quantity([1.0, 2.0, 3.0, 4.0], "currency/J"))
    with raises(gm.errors.ValidationError, "invalid_value", match="one per step"):
        level(case, PATH, 3)


def test_an_absent_price_is_missing_assumption():
    """Nothing in the case, nothing assumed."""
    with raises(gm.errors.ValidationError, "missing_assumption", match=r"opex\.electricity"):
        level(make_case(finance={"currency": "EUR"}), PATH, 4)
