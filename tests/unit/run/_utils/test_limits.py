"""The constraints a schedule enforces, found by their general form."""

import pandas as pd
import pytest

import gemini as gm
from gemini.run._utils import limits
from tests.fixtures.errors import raises

FLOW = gm.Constraint(
    "d*.reservoir.liquid_flow",
    min={"value": 50, "unit": "m3/h"},
    max={"value": 300, "unit": "m3/h"},
    when="running",
)
COOLING = gm.Constraint("d*.brine_cooling", max={"value": 40, "unit": "K"}, when="running")
DURATION = gm.Constraint(
    "d*.reservoir.liquid_flow", max={"value": 330, "unit": "d"}, over="duration", when="running"
)


def test_a_doublet_gets_its_limits_in_si():
    """The flow range, the cooling and the running time of every doublet that fits."""
    found, check_only = limits.split([FLOW, COOLING, DURATION], ["d0"])
    assert found["d0"].minimum_flow == pytest.approx(50 / 3600)
    assert found["d0"].brine_cooling == 40
    assert found["d0"].operating_time == pd.Timedelta(days=330)
    assert check_only == []


def test_what_the_schedule_cannot_enforce_is_check_only():
    """Another field, or a duration with only a minimum, is left to the check of a run."""
    other = gm.Constraint("users.supply_in.temperature", min={"value": 100, "unit": "degC"})
    least = gm.Constraint(
        "d*.reservoir.liquid_flow", min={"value": 1, "unit": "d"}, over="duration", when="running"
    )
    found, check_only = limits.split([FLOW, COOLING, other, least], ["d0"])
    assert check_only == [other.to_dict(), least.to_dict()] and found["d0"].operating_time is None


@pytest.mark.parametrize("constraints,name", [([COOLING], "liquid_flow"), ([FLOW], "brine_cool")])
def test_a_limit_the_schedule_needs_is_named(constraints, name):
    """A flow range and a brine cooling are required, per doublet."""
    with raises(gm.errors.ValidationError, "missing_value", match=name):
        limits.split(constraints, ["d0"])


def test_a_star_stays_within_a_name():
    """``d*`` fits a doublet and not what lies below it."""
    found, _ = limits.split([FLOW, COOLING], ["d0", "d1"])
    assert set(found) == {"d0", "d1"}


def _left_of(*constraints):
    """Return what the schedule leaves to a check, with the required limits given."""
    return limits.split([FLOW, COOLING, *constraints], ["d0"])


def test_a_duration_with_a_maximum_and_a_minimum_leaves_the_minimum_to_the_check():
    """The schedule enforces the maximum; only the minimum is listed, and it stays exact."""
    both = gm.Constraint(
        "d*.reservoir.liquid_flow",
        min={"value": 300, "unit": "d"},
        max={"value": 330, "unit": "d"},
        over="duration",
        when="running",
    )
    found, check_only = _left_of(both)
    assert found["d0"].operating_time == pd.Timedelta(days=330)
    assert check_only == [
        {
            "path": "d*.reservoir.liquid_flow",
            "min": {"value": 300, "unit": "d"},
            "max": None,
            "equals": None,
            "over": "duration",
            "when": "running",
        }
    ]


def test_a_duration_with_equals_and_a_bound_leaves_the_bound():
    """``equals`` is what the schedule runs; the other bound is left to the check."""
    both = gm.Constraint(
        "d*.reservoir.liquid_flow",
        equals={"value": 320, "unit": "d"},
        max={"value": 330, "unit": "d"},
        over="duration",
        when="running",
    )
    found, check_only = _left_of(both)
    assert found["d0"].operating_time == pd.Timedelta(days=320)
    assert [(item["equals"], item["max"]) for item in check_only] == [
        (None, {"value": 330, "unit": "d"})
    ]


def test_a_minimum_on_the_brine_cooling_is_left_to_the_check():
    """The schedule enforces the maximum of a cooling and nothing below it."""
    cooling = gm.Constraint(
        "d*.brine_cooling",
        min={"value": 5, "unit": "K"},
        max={"value": 40, "unit": "K"},
        when="running",
    )
    _, check_only = limits.split([FLOW, cooling], ["d0"])
    assert [(item["min"], item["max"]) for item in check_only] == [
        ({"value": 5, "unit": "K"}, None)
    ]


def test_what_is_enforced_whole_is_not_listed():
    """A flow range and a maximum are enforced as they stand."""
    assert _left_of()[1] == []
    only_maximum = gm.Constraint(
        "d*.reservoir.liquid_flow", max={"value": 330, "unit": "d"}, over="duration", when="running"
    )
    assert _left_of(only_maximum)[1] == []
