"""The constraints a schedule enforces, found by their role and quantity."""

import pandas as pd
import pytest

import gemini as gm
from gemini.run._utils import limits
from gemini.units import Quantity
from tests.fixtures.errors import raises


def constraint(quantity, on="doublet", **fields):
    """Return a constraint of ``on`` and ``quantity`` with bounds in the dict form."""
    bounds = {name: Quantity(*value) for name, value in fields.pop("bounds").items()}
    return gm.case.Constraint(on=on, quantity=quantity, **bounds, **fields)


FLOW = constraint(
    "production_flow", when="running", bounds={"min": (50, "m3/h"), "max": (300, "m3/h")}
)
COOLING = constraint("brine_cooling", when="running", bounds={"max": (40, "K")})
DURATION = constraint(
    "production_flow", over="duration", when="running", bounds={"max": (330, "d")}
)


def test_a_doublet_gets_its_limits_in_si():
    """The flow range, the cooling and the running time of every doublet."""
    found, check_only = limits.split([FLOW, COOLING, DURATION], ["d0"])
    assert found["d0"].minimum_flow == pytest.approx(50 / 3600)
    assert found["d0"].brine_cooling == 40
    assert found["d0"].operating_time == pd.Timedelta(days=330)
    assert check_only == []


def test_a_constraint_applies_to_every_doublet_whatever_its_name():
    """The role, not a path, says which units a constraint limits."""
    found, _ = limits.split([FLOW, COOLING], ["well_a", "d1"])
    assert set(found) == {"well_a", "d1"}


def test_what_the_schedule_cannot_enforce_is_check_only():
    """Another role, or a duration with only a minimum, is left to the check of a run."""
    other = constraint("temperature", on="heating_supply", bounds={"min": (100, "degC")})
    least = constraint("production_flow", over="duration", when="running", bounds={"min": (1, "d")})
    found, check_only = limits.split([FLOW, COOLING, other, least], ["d0"])
    assert check_only == [other.to_dict(), least.to_dict()] and found["d0"].operating_time is None


@pytest.mark.parametrize(
    "constraints,name", [([COOLING], "production_flow"), ([FLOW], "brine_cool")]
)
def test_a_limit_the_schedule_needs_is_named(constraints, name):
    """A flow range and a brine cooling are required."""
    with raises(gm.errors.ValidationError, "missing_value", match=name):
        limits.split(constraints, ["d0"])


def _left_of(*constraints):
    """Return what the schedule leaves to a check, with the required limits given."""
    return limits.split([FLOW, COOLING, *constraints], ["d0"])


def test_a_duration_with_a_maximum_and_a_minimum_leaves_the_minimum_to_the_check():
    """The schedule enforces the maximum; only the minimum is listed, and it stays exact."""
    both = constraint(
        "production_flow",
        over="duration",
        when="running",
        bounds={"min": (300, "d"), "max": (330, "d")},
    )
    found, check_only = _left_of(both)
    assert found["d0"].operating_time == pd.Timedelta(days=330)
    assert len(check_only) == 1
    assert (
        check_only[0]["min"]["value"] == pytest.approx(300 * 86400) and "max" not in check_only[0]
    )


def test_a_duration_with_equals_and_a_bound_leaves_the_bound():
    """``equals`` is what the schedule runs; the other bound is left to the check."""
    both = FLOW.model_copy(
        update={"over": "duration", "min": None, "max": 330 * 86400.0, "equals": 320 * 86400.0}
    )
    found, check_only = _left_of(both)
    assert found["d0"].operating_time == pd.Timedelta(days=320)
    assert [("equals" in item, item["max"]["value"]) for item in check_only] == [
        (False, 330 * 86400.0)
    ]


def test_a_minimum_on_the_brine_cooling_is_left_to_the_check():
    """The schedule enforces the maximum of a cooling and nothing below it."""
    cooling = constraint(
        "brine_cooling", when="running", bounds={"min": (5, "K"), "max": (40, "K")}
    )
    _, check_only = limits.split([FLOW, cooling], ["d0"])
    assert [(item["min"]["value"], "max" in item) for item in check_only] == [(5.0, False)]


def test_what_is_enforced_whole_is_not_listed():
    """A flow range and a maximum are enforced as they stand."""
    assert _left_of()[1] == []
    assert _left_of(DURATION)[1] == []
