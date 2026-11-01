"""``gm.case.Time``: the period of a run, its end excluded."""

import pandas as pd
import pytest

import gemini as gm
from gemini.units import Quantity
from tests.fixtures.errors import raises


def test_a_year_at_one_day_is_365_steps():
    """``end`` is excluded: 2027-01-01 to 2028-01-01 is 365 days."""
    time = gm.case.Time(start="2027-01-01", end="2028-01-01", step=Quantity(1, "d"))
    assert len(time.index) == 365 and time.index[-1] == pd.Timestamp("2027-12-31", tz="UTC")
    assert time.index.name == "time" and time.step == 86400.0


def test_the_dict_round_trip_keeps_dates_and_writes_the_step_in_seconds():
    """A date at midnight is a date, and the step is SI."""
    time = gm.case.Time(start="2027-01-01", end="2027-01-02", step=Quantity(1, "h"))
    assert time.to_dict() == {
        "start": "2027-01-01",
        "end": "2027-01-02",
        "step": {"value": 3600.0, "unit": "s"},
    }
    assert gm.case.Time.from_dict(time.to_dict()) == time


def test_a_period_of_a_part_of_a_step_is_refused():
    """The end must follow the start by whole steps."""
    with raises(gm.errors.ValidationError, "invalid_value"):
        gm.case.Time(start="2027-01-01", end="2027-01-02", step=Quantity(5, "h"))


def test_an_end_before_the_start_is_out_of_bounds():
    """An empty period is refused."""
    with raises(gm.errors.ValidationError, "out_of_bounds"):
        gm.case.Time(start="2027-01-02", end="2027-01-01", step=Quantity(1, "d"))


def test_text_for_the_step_is_refused():
    """A step is a quantity, never text."""
    with raises(gm.errors.ValidationError, "invalid_value") as caught:
        gm.case.Time(start="2027-01-01", end="2027-01-08", step="1 d")
    assert "time.step" in str(caught.value)


@pytest.mark.parametrize("value", ["not a date", 5])
def test_a_start_that_is_no_date_is_refused(value):
    """The start is an ISO-8601 date or a datetime."""
    with raises(gm.errors.ValidationError, "invalid_value"):
        gm.case.Time(start=value, end="2027-01-08", step=Quantity(1, "d"))
