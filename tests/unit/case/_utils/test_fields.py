"""The field types of the case: quantities in SI, maps and schemas."""

import numpy as np
import pytest

import gemini as gm
from gemini.case._utils import fields
from gemini.units import Quantity
from tests.fixtures.errors import raises


def test_a_quantity_or_its_dict_converts_to_si():
    """Offsets apply, differences do not."""
    assert fields.to_si(Quantity(12, "degC"), "temperature") == pytest.approx(285.15)
    assert fields.to_si({"value": 40, "unit": "degC"}, "temperature_difference") == 40.0
    assert fields.si_unit_of("volume_flow") == "m3/s"


def test_a_plain_number_is_for_a_dimensionless_quantity_only():
    """0.7 is an efficiency; 5 is not a length."""
    assert fields.to_si(0.7, "efficiency") == 0.7
    with raises(gm.errors.ValidationError, "invalid_value"):
        fields.to_si(5, "length")
    with raises(gm.errors.ValidationError, "invalid_value"):
        fields.to_si("5 m", "length")
    with raises(gm.errors.ValidationError, "invalid_value"):
        fields.to_si(True, "efficiency")


def test_a_unit_of_another_dimension_lists_the_units_of_the_field():
    """The message says what was expected."""
    with raises(gm.errors.ValidationError, "invalid_unit") as caught:
        fields.to_si(Quantity(1, "m"), "volume_flow")
    assert "not a volume flow" in str(caught.value) and "m3/h" in str(caught.value)


def test_a_profile_is_an_array_only_where_allowed():
    """A list is refused by a field without a profile."""
    assert list(fields.to_si(Quantity([1.0, 2.0], "kW"), "power", profile=True)) == [1000, 2000]
    with raises(gm.errors.ValidationError, "invalid_value"):
        fields.to_si(Quantity([1.0], "kW"), "power")
    with raises(gm.errors.ValidationError, "invalid_value"):
        fields.to_si(Quantity(float("nan"), "kW"), "power")


def test_bounds_are_checked_in_si():
    """Strict and non-strict minimum and maximum."""
    field = fields.Q("length", minimum=(0.0, True), maximum=(10.0, False))
    assert field.convert(Quantity(10, "m")) == 10.0 and field.convert(None) is None
    with raises(gm.errors.ValidationError, "out_of_bounds"):
        field.convert(Quantity(0, "m"))
    with raises(gm.errors.ValidationError, "out_of_bounds"):
        field.convert(Quantity(11, "m"))


def test_a_map_has_known_keys_and_si_values():
    """Unknown keys are ``unknown_name``."""
    field = fields.QMap("annual_rate", ("a", "b"))
    assert field.convert({"a": Quantity(2, "%/yr")}) == {"a": pytest.approx(0.02)}
    with raises(gm.errors.ValidationError, "unknown_name"):
        field.convert({"c": Quantity(2, "%/yr")})
    with raises(gm.errors.ValidationError, "invalid_value"):
        field.convert([1])


def test_quantity_dict_and_schema():
    """A dimensionless scalar stays a number; the schema lists the units."""
    assert fields.quantity_dict(285.15, "temperature") == {"value": 285.15, "unit": "K"}
    assert fields.quantity_dict(0.7, "efficiency") == 0.7
    assert fields.quantity_dict(np.array([1.0]), "power") == {"value": [1.0], "unit": "W"}
    schema = fields.quantity_schema("pressure")
    assert (
        schema["additionalProperties"] is False and "barg" in schema["properties"]["unit"]["enum"]
    )
    assert "anyOf" in fields.quantity_schema("efficiency")
    assert fields.is_number(1.5) and not fields.is_number(True)
