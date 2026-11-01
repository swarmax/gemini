"""``gm.case.Constraint``: a limit on a quantity of a role."""

import pytest

import gemini as gm
from gemini.units import Quantity
from tests.fixtures.errors import raises


def test_bounds_are_stored_in_si():
    """150 m3/h is a volume flow in m3/s and a duration bound is in seconds."""
    flow = gm.case.Constraint(
        on="doublet",
        quantity="production_flow",
        when="running",
        min=Quantity(50, "m3/h"),
        max=Quantity(300, "m3/h"),
    )
    assert flow.min == pytest.approx(50 / 3600) and flow.over == "each"
    days = gm.case.Constraint(
        on="doublet", quantity="production_flow", over="duration", max=Quantity(330, "d")
    )
    assert days.max == 330 * 86400.0 and days.to_dict()["max"] == {"value": 28512000.0, "unit": "s"}


def test_a_temperature_difference_has_no_offset():
    """40 K is 40 in SI, with no offset."""
    cooling = gm.case.Constraint(on="doublet", quantity="brine_cooling", max=Quantity(40, "K"))
    assert cooling.max == 40.0


def test_a_dimensionless_bound_takes_a_plain_number():
    """An efficiency is a number."""
    assert gm.case.Constraint(on="doublet", quantity="pump_efficiency", equals=0.7).equals == 0.7


def test_the_round_trip_through_a_dict():
    """to_dict and from_dict keep the constraint."""
    constraint = gm.case.Constraint(
        on="heating_supply", quantity="temperature", min=Quantity(95, "degC"), when="running"
    )
    assert gm.case.Constraint.from_dict(constraint.to_dict()) == constraint


def test_a_quantity_outside_its_role_lists_the_role_quantities():
    """``cop`` is no quantity of a doublet."""
    with raises(gm.errors.ValidationError, "invalid_value") as caught:
        gm.case.Constraint(on="doublet", quantity="cop", max=5)
    assert "production_flow" in str(caught.value) and "'cop'" in str(caught.value)


def test_an_unknown_role_is_unknown_name():
    """The roles are closed."""
    with raises(gm.errors.ValidationError, "unknown_name"):
        gm.case.Constraint(on="pump", quantity="cop", max=5)


def test_a_bound_of_another_dimension_is_invalid_unit():
    """A length is no volume flow."""
    with raises(gm.errors.ValidationError, "invalid_unit") as caught:
        gm.case.Constraint(on="doublet", quantity="production_flow", max=Quantity(300, "m"))
    assert "not a volume flow" in str(caught.value) and "m3/h" in str(caught.value)


def test_a_plain_number_with_a_dimension_is_invalid_value():
    """Only a dimensionless quantity takes a number."""
    with raises(gm.errors.ValidationError, "invalid_value"):
        gm.case.Constraint(on="doublet", quantity="production_flow", max=300)


def test_a_constraint_needs_a_bound_and_one_kind():
    """No bound is ``missing_value``; ``equals`` with a range is ``conflicting_value``."""
    with raises(gm.errors.ValidationError, "missing_value"):
        gm.case.Constraint(on="doublet", quantity="pump_efficiency")
    with raises(gm.errors.ValidationError, "conflicting_value"):
        gm.case.Constraint(on="doublet", quantity="pump_efficiency", equals=0.7, max=0.9)
    with raises(gm.errors.ValidationError, "out_of_bounds"):
        gm.case.Constraint(on="doublet", quantity="pump_efficiency", min=0.9, max=0.7)


def test_over_and_when_are_closed():
    """Only the listed values."""
    with raises(gm.errors.ValidationError, "invalid_value"):
        gm.case.Constraint(on="doublet", quantity="pump_efficiency", equals=0.7, over="total")
    with raises(gm.errors.ValidationError, "invalid_value"):
        gm.case.Constraint(on="doublet", quantity="pump_efficiency", equals=0.7, when="never")
