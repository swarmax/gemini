"""The corrosion forecast against the original de Waard-Lotz reference and hand formulas."""

import math

import pytest

import gemini as gm
from gemini import units
from gemini.analysis import integrity
from gemini.physics import corrosion

MODEL = {
    "correlation": "DLM",
    "conditions": {
        "temperature": {"value": 50, "unit": "degC"},
        "pressure": {"value": 3, "unit": "bar"},
        "co2_fraction": 1,
        "water_flow_rate": math.pi * 0.1**2 / 4,
        "diameter": 0.1,
    },
    "thickness": 0.010,
    "minimum_thickness": 0.007,
    "start": "2024-01-01T00:00:00Z",
}
"""Original reference case: 50 degC, 3 bar, pure CO2, 1 m/s in 0.1 m pipe; 6.7 mm/year."""


@pytest.fixture(scope="module")
def forecast():
    """Return the forecast of the reference case over 2.5 years."""
    return integrity.corrosion_forecast(MODEL, "2026-07-01T00:00:00Z")


def test_rate_is_the_original_reference_value(forecast):
    """DLM at 50 degC and 3 bar corrodes 6.7 mm/year, the retained original test."""
    assert forecast["rate"]["value"] == pytest.approx(6.7, abs=0.05)
    assert forecast["rate"]["unit"] == "mm/year"


def test_thickness_falls_linearly_with_the_rate(forecast):
    """After each whole year the wall has lost rate times years, in metres."""
    wall = forecast["thickness"]
    rate = forecast["rate"]["value"]
    for years, thickness in enumerate(wall["value"][:-1]):
        assert thickness == pytest.approx(0.010 - rate / 1000 * years, rel=1e-12)
    assert len(wall["time"]) == len(wall["value"]) == 4 and wall["unit"] == "m"
    assert wall["time"][-1] == "2026-07-01T00:00:00+00:00"


def test_years_left_is_the_remaining_wall_over_the_rate(forecast):
    """3 mm of allowance at the rate gives the years to the minimum wall."""
    assert forecast["years_left"]["value"] == pytest.approx(3 / forecast["rate"]["value"], rel=1e-9)


def test_a_wall_at_its_minimum_has_no_time_left():
    """Zero years left, not a negative number."""
    worn = dict(MODEL, thickness=0.007)
    forecast = integrity.corrosion_forecast(worn, "2025-01-01T00:00:00Z")
    assert forecast["years_left"] == {"value": 0.0, "unit": "yr"}


def test_the_rate_matches_the_physics_function_in_si(forecast):
    """Unit strings and SI numbers give the same rate as calling the correlation directly."""
    direct = corrosion.co2_corrosion_rate(
        "DLM",
        temperature=units.c_to_k(50),
        pressure=units.bar_to_pa(3),
        co2_fraction=1,
        water_flow_rate=math.pi * 0.1**2 / 4,
        diameter=0.1,
    )
    assert forecast["rate"]["value"] == direct


def test_inputs_are_checked():
    """An end before the start and an unknown condition are refused with a suggestion."""
    with pytest.raises(gm.errors.ValidationError, match="after the start"):
        integrity.corrosion_forecast(MODEL, "2023-01-01T00:00:00Z")
    bad = dict(MODEL, conditions=dict(MODEL["conditions"], temprature=300))
    with pytest.raises(gm.errors.ValidationError, match="temperature") as error:
        integrity.corrosion_forecast(bad, "2025-01-01T00:00:00Z")
    assert error.value.suggestions == ("temperature",)


def test_calibration_and_erosion_are_not_built_yet():
    """Both keep their final signature and say so."""
    with pytest.raises(gm.errors.NotImplementedYet):
        integrity.calibrate_corrosion([])
    with pytest.raises(gm.errors.NotImplementedYet):
        integrity.erosion(None, "doublet")


def test_the_forecast_takes_units_for_the_wall():
    """The rate stays in its literature unit."""
    forecast = integrity.corrosion_forecast(MODEL, "2026-07-01T00:00:00Z", units={"length": "mm"})
    assert forecast["thickness"]["unit"] == "mm" and forecast["minimum_thickness"]["unit"] == "mm"
    assert forecast["thickness"]["value"][0] == pytest.approx(10.0)
    assert forecast["rate"]["unit"] == "mm/year"
