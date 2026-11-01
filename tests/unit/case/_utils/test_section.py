"""The base of the case sections: errors, equality, dicts and schemas."""

import numpy as np
import pytest

import gemini as gm
from gemini.case._utils import section
from gemini.units import Quantity
from tests.fixtures.errors import raises


def test_a_section_is_strict_and_frozen():
    """Unknown keys fail and nothing is set afterwards."""
    ground = gm.case.Ground(gradient=Quantity(30, "K/km"))
    with pytest.raises(Exception):
        ground.gradient = 1.0
    with raises(gm.errors.ValidationError, "unknown_name"):
        gm.case.Ground(slope=1)


def test_a_failure_names_the_path_and_the_code():
    """A bound below zero is out of bounds, at the path of the field."""
    with raises(gm.errors.ValidationError, "out_of_bounds") as caught:
        gm.case.Reservoir(thickness=Quantity(-1, "m"))
    assert caught.value.path == "environment.reservoir.thickness"


def test_the_outermost_section_reports_with_the_whole_path():
    """A nested failure carries the path from the case."""
    with raises(gm.errors.ValidationError, "out_of_bounds") as caught:
        gm.case.Environment(reservoir={"thickness": {"value": -1, "unit": "m"}})
    assert caught.value.path == "environment.reservoir.thickness"


def test_a_non_dict_is_refused_by_from_dict():
    """``from_dict`` takes a dict."""
    with raises(gm.errors.ValidationError, "invalid_value"):
        gm.case.Ground.from_dict([1])


def test_equality_compares_arrays_by_value():
    """Two airs with equal profiles are equal; different ones are not."""
    one = gm.case.Air(temperature=Quantity([1.0, 2.0], "K"))
    assert one == gm.case.Air(temperature=Quantity([1.0, 2.0], "K"))
    assert one != gm.case.Air(temperature=Quantity([1.0, 3.0], "K"))
    assert one != gm.case.Ground()


def test_same_compares_nested_values():
    """Arrays, lists and dicts."""
    assert section.same({"a": np.array([1, 2])}, {"a": np.array([1, 2])})
    assert not section.same([1, 2], [1])
    assert section.same((1, 2), [1, 2])


def test_the_schema_of_a_section_is_closed_and_lists_required_keys():
    """Required fields have no default."""
    schema = gm.case.Constraint.schema()
    assert schema["additionalProperties"] is False and schema["required"] == ["on", "quantity"]
    assert schema["properties"]["over"]["enum"][0] == "each"
    assert schema["properties"]["when"]["enum"] == ["always", "running"]
    assert gm.case.Demand.schema()["required"] == ["file"]
    assert "frame" not in gm.case.Demand.schema()["properties"]
