"""The one rule for a value with a dimension: a quantity, never a bare number."""

import numpy as np
import pytest

from gemini.errors import ValidationError
from gemini.types import bare
from tests.fixtures.errors import raises


@pytest.mark.parametrize("value", [0, 1.5, np.float64(2.0), np.array([1.0]), [1.0, 2.0], (1, 2)])
def test_a_number_an_array_or_a_list_is_bare(value):
    """Zero is bare too."""
    assert bare.is_bare(value)


@pytest.mark.parametrize("value", [True, None, "10 m", {"value": 1, "unit": "m"}])
def test_a_flag_text_none_or_a_dict_is_not_bare(value):
    """A dict is the JSON form of a quantity and is checked by its unit later."""
    assert not bare.is_bare(value)


def test_refuse_names_the_path_the_quantity_and_the_accepted_units():
    """The message and the path of the error are those of every public boundary."""
    with raises(ValidationError, "invalid_value", match="a.b = 0; expected a Quantity") as caught:
        bare.refuse("a.b", 0, "m", "length")
    assert caught.value.path == "a.b"
    assert "length in 'm'" in str(caught.value) and "accepted units: " in str(caught.value)
    assert "km" in str(caught.value)


def test_refuse_names_only_the_unit_without_a_quantity():
    """A declaration without a named quantity still says its unit."""
    with raises(ValidationError, "invalid_value", match="unit 'W'"):
        bare.refuse("x", 3.0, "W")


@pytest.mark.parametrize("unit", [None, "-"])
def test_a_dimensionless_value_stays_a_number(unit):
    """Efficiencies, fractions, counts and ratios are plain numbers."""
    bare.refuse("x", 0.5, unit)
    bare.refuse("x", 3, unit, "fraction")
