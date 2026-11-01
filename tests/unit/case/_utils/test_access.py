"""Reading a value of a case, or the error that names its path."""

import numpy as np
import pytest

import gemini as gm
from gemini.case._utils import access
from tests.fixtures.errors import raises


@pytest.fixture
def case(data, folder):
    """Return the full sample case."""
    return gm.Case.from_dict(data, folder)


def test_a_present_value_is_returned(case):
    """Paths walk attributes and dicts."""
    assert access.require(case, "environment.reservoir.thickness") == 100.0
    assert access.require(case, "assumptions.finance.opex.fixed.heat_pump") == pytest.approx(0.02)


def test_an_absent_value_names_its_path(case):
    """``missing_value`` outside the assumptions."""
    with raises(gm.errors.ValidationError, "missing_value") as caught:
        access.require(case, "environment.reservoir.temperature")
    assert caught.value.path == "environment.reservoir.temperature"
    assert "has no default" in str(caught.value)


def test_an_absent_assumption_is_missing_assumption(case):
    """The code follows the first part of the path."""
    with raises(gm.errors.ValidationError, "missing_assumption") as caught:
        access.require(case, "assumptions.finance.capex.boiler")
    assert caught.value.path == "assumptions.finance.capex.boiler"
    with raises(gm.errors.ValidationError, "missing_assumption"):
        access.require(case, "assumptions.finance.opex.fixed.boiler")


def test_a_prefix_completes_the_path(case):
    """A section read on its own still names the whole path."""
    with raises(gm.errors.ValidationError, "missing_value") as caught:
        access.require(case.environment, "air.humidity", "environment")
    assert caught.value.path == "environment.air.humidity"


def test_a_series_repeats_a_constant_on_every_step(case):
    """The air is constant in the sample; the result has one value per step."""
    values = access.series(case, "environment.air.temperature")
    assert np.allclose(values, 283.15) and len(values) == 7
