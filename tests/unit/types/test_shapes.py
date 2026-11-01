"""The three return shapes: one helper and one schema each."""

import json
import math

import numpy as np
import pytest

import gemini as gm
from gemini.types import shapes
from tests.fixtures import ROOT
from tests.fixtures.errors import raises
from tests.fixtures.json_schema import check

SCHEMAS = ROOT / "docs" / "schemas"


def fits(document, name):
    """Return the problems of a document against the stored schema of a shape."""
    return check(document, json.loads((SCHEMAS / f"{name}.schema.json").read_text()))


def test_a_value_has_its_unit_and_no_reason():
    """A number or an array travels with its unit."""
    assert shapes.value(3.0, "W") == {"value": 3.0, "unit": "W"}
    assert shapes.value([1.0, None], "W") == {"value": [1.0, None], "unit": "W"}
    assert fits(shapes.value(3.0, "W"), "value") == []


@pytest.mark.parametrize("number", [None, math.nan, math.inf])
def test_a_missing_value_says_why(number):
    """``None``, NaN and infinity are null, and a null value always has a reason."""
    assert shapes.value(number, "W", "no flow") == {"value": None, "unit": "W", "reason": "no flow"}
    assert shapes.value(number, "W")["reason"] == shapes.NO_VALUE
    json.dumps(shapes.value(number, "W"), allow_nan=False)
    assert fits(shapes.value(number, "W"), "value") == []


def test_a_null_value_without_a_reason_does_not_fit_the_schema():
    """The schema holds the rule, so a hand-built shape fails."""
    assert fits({"value": None, "unit": "W"}, "value")


def test_details_follow_the_keys_of_the_shape():
    """The fixed keys come first, details after, and a NaN becomes null."""
    result = shapes.value(float("nan"), "EUR", "why", capex=shapes.value(3.0, "EUR"))
    assert list(result) == ["value", "unit", "reason", "capex"]
    assert result["capex"] == {"value": 3.0, "unit": "EUR"}
    json.dumps(result, allow_nan=False)
    assert fits(result, "value") == []


def test_a_series_is_a_value_with_a_time_axis():
    """The key is ``value`` for arrays too."""
    series = shapes.series(["2024-01-01T00:00:00+00:00"], [1.0], "K")
    assert series == {"time": ["2024-01-01T00:00:00+00:00"], "value": [1.0], "unit": "K"}
    assert fits(series, "value") == []


def test_statistics_are_three_values():
    """Each of min, max and mean is a value; one without a number says why."""
    result = shapes.statistics(1.0, 3.0, math.nan, "W")
    assert result["min"] == {"value": 1.0, "unit": "W"}
    assert result["max"] == {"value": 3.0, "unit": "W"}
    assert result["mean"]["value"] is None and result["mean"]["reason"]


def test_a_problem_has_four_keys_and_a_run_row_adds_the_time():
    """There is no class key: ``code`` is the stable key for machines."""
    assert shapes.problem("a.b", "unknown_name", "no such name", ("x",)) == {
        "path": "a.b",
        "code": "unknown_name",
        "message": "no such name",
        "suggestions": ["x"],
    }
    row = shapes.problem("a", "module_error", ValueError("boom"), time="2024-01-01T00:00:00+00:00")
    assert row["time"] == "2024-01-01T00:00:00+00:00" and row["message"] == "boom"
    assert fits(row, "problem") == []


def test_a_decided_check_has_four_keys():
    """name, passed, value and limit, the last two values."""
    result = shapes.check("x", True, shapes.value(1.5, "W"), shapes.value(0.1, "W"))
    assert result == {
        "name": "x",
        "passed": True,
        "value": {"value": 1.5, "unit": "W"},
        "limit": {"value": 0.1, "unit": "W"},
    }
    assert fits(result, "check") == []


def test_an_undecided_check_carries_its_reason_in_the_value_and_stays_json():
    """``passed`` None has a null value with the reason; a NaN value becomes null."""
    measured = shapes.value(float("nan"), "W", "nothing to judge")
    result = shapes.check("x", None, measured, shapes.value(0.1, "W"))
    assert result["passed"] is None and result["value"]["reason"] == "nothing to judge"
    json.dumps(result, allow_nan=False)
    assert fits(result, "check") == []


def test_a_check_with_a_bare_number_does_not_fit_the_schema():
    """``value`` and ``limit`` are values, not numbers."""
    assert fits({"name": "x", "passed": True, "value": 1.5, "limit": 0.1}, "check")


def test_the_problem_of_an_error_is_the_shape():
    """``to_dict`` and the helper give the same keys in the same order."""
    error = gm.errors.ValidationError("bad", path="a", code="invalid_value")
    assert error.to_dict() == shapes.problem("a", "invalid_value", "bad")
    assert fits(error.to_dict(), "problem") == []


def test_the_shapes_export_the_one_problem_helper():
    """``gemini.errors`` is a leaf, so the helper is defined there and exported here."""
    assert shapes.problem is gm.errors.base.problem


def test_output_units_convert_a_value_and_say_the_unit_used():
    """The returned unit is the one actually used."""
    output = shapes.OutputUnits({"power": "MW", "temperature": "degC"})
    assert output.value(2e6, "W", "power") == {"value": 2.0, "unit": "MW"}
    assert output.value(373.15, "K", "temperature")["value"] == pytest.approx(100.0)
    assert output.value(373.15, "K", "temperature")["unit"] == "degC"


def test_a_key_reaches_its_family_and_an_exact_key_wins():
    """``power`` reaches a duty; a duty named in the map keeps its own unit."""
    assert shapes.OutputUnits({"power": "MW"}).value(1e6, "W", "duty")["unit"] == "MW"
    both = shapes.OutputUnits({"power": "MW", "duty": "kW"})
    assert both.value(1e6, "W", "duty") == {"value": 1000.0, "unit": "kW"}
    assert both.value(1e6, "W", "electricity")["unit"] == "MW"


def test_a_difference_converts_by_scale_only():
    """A temperature difference has no offset and a pressure difference no gauge offset."""
    output = shapes.OutputUnits({"temperature": "degC", "pressure": "barg"})
    assert output.value(5.0, "K", "temperature_difference") == {"value": 5.0, "unit": "degC"}
    assert output.value(5e5, "Pa", "pressure_difference") == {"value": 5.0, "unit": "barg"}
    absolute = output.value(5e5, "Pa", "pressure")["value"]
    assert absolute == pytest.approx((5e5 - 101325) / 1e5)


def test_without_a_map_nothing_changes():
    """Outputs stay SI by default, the same object included."""
    numbers = [1.0, 2.0]
    assert shapes.OutputUnits().number(numbers, "W", "power") == (numbers, "W")
    assert shapes.OutputUnits({"pressure": "bar"}).number(1.0, "W", "power") == (1.0, "W")
    assert shapes.OutputUnits({"pressure": "bar"}).number(1.0, "-", None) == (1.0, "-")


def test_arrays_lists_and_gaps_convert_item_by_item():
    """A null and a text stay; a nested list keeps its shape."""
    output = shapes.OutputUnits({"power": "kW"})
    assert output.number([1000.0, None, [2000.0]], "W", "power")[0] == [1.0, None, [2.0]]
    assert output.number(np.array([1000.0]), "W", "power")[0].tolist() == [1.0]
    assert output.number("text", "W", "power")[0] == "text"


def test_a_series_and_statistics_take_the_unit_too():
    """Every shape helper has its converting form."""
    output = shapes.OutputUnits({"power": "kW"})
    assert output.series(["t"], [1000.0], "W", "power") == {
        "time": ["t"],
        "value": [1.0],
        "unit": "kW",
    }
    assert output.statistics(1e3, 2e3, 1.5e3, "W", "power")["mean"] == {"value": 1.5, "unit": "kW"}


def test_an_unknown_quantity_raises_with_suggestions():
    """The map is checked at the start of a call."""
    with raises(gm.errors.ValidationError, "unknown_name") as caught:
        shapes.OutputUnits({"powr": "MW"})
    assert "power" in caught.value.suggestions


def test_a_unit_that_does_not_fit_raises_with_suggestions():
    """A unit of another dimension names the units of the quantity."""
    with raises(gm.errors.ValidationError, "invalid_unit", match="units: power = 'bar'"):
        shapes.OutputUnits({"power": "bar"})
    with raises(gm.errors.ValidationError, "invalid_unit") as caught:
        shapes.OutputUnits({"power": "MWW"})
    assert "MW" in caught.value.suggestions


def test_measure_holds_a_python_float_for_a_numpy_scalar():
    """A public return holds no NumPy type."""
    measured = shapes.measure(np.float64(2.5), "W")
    assert type(measured.value) is float
    assert measured.value == 2.5
