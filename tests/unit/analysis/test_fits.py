"""Fits of model parameters to measurements."""

import numpy as np
import pytest

from gemini import analysis
from gemini.errors import PhysicsError, ValidationError
from gemini.modules.pumps import _physics
from tests.fixtures.errors import raises

CURVE = [83.08389282, -0.000460444, -1.19e-07, 1.69e-11, -6.36e-16, 6.69e-21]


def test_fit_head_coefficients_recovers_the_curve():
    """A fit of synthetic heads predicts a withheld point of the same curve."""
    flows = np.linspace(0.01, 0.06, 20)
    frequencies = np.linspace(40, 60, 20)
    heads = [_physics.head(q, f, 12, CURVE) for q, f in zip(flows, frequencies)]
    fitted = analysis.fit_head_coefficients(flows, frequencies, heads, 12)["value"]
    assert _physics.head(0.037, 53, 12, fitted) == pytest.approx(
        _physics.head(0.037, 53, 12, CURVE), rel=1e-9
    )


def test_fit_head_coefficients_refuses_too_few_or_invalid_observations():
    """Fewer than six points, repeated flows or a nonpositive frequency are insufficient."""
    with raises(PhysicsError, "too_little_data", match="six matching"):
        analysis.fit_head_coefficients([1, 2], [50, 50], [1, 2], 12)
    with raises(PhysicsError, "too_little_data", match="six distinct"):
        analysis.fit_head_coefficients([0.01] * 6, [50] * 6, list(range(6)), 12)
    with raises(PhysicsError, "too_little_data", match="finite positive"):
        analysis.fit_head_coefficients([0.01] * 6, [0] * 6, list(range(6)), 12)


def test_fit_head_correction_is_the_least_squares_line():
    """Exact points give the slope and the offset of their line."""
    fitted = analysis.fit_head_correction([1, 2, 3], [3, 5, 7])
    assert fitted["slope"]["value"] == pytest.approx(2) and fitted["slope"]["unit"] == "-"
    assert fitted["offset"]["value"] == pytest.approx(1) and fitted["offset"]["unit"] == "Pa"
    with raises(PhysicsError, "too_little_data", match="distinct"):
        analysis.fit_head_correction([1, 1], [3, 5])


def test_estimate_reservoir_pressure_finds_the_linear_inflow_pressure():
    """Points of ``p_bh = p_res + b Q`` give ``p_res`` and an R-squared of one."""
    flows = np.array([0.01, 0.02, 0.04])
    estimate = analysis.estimate_reservoir_pressure(flows, 2e7 - 1e8 * flows)
    assert estimate["pressure"]["value"] == pytest.approx(2e7)
    assert estimate["pressure"]["unit"] == "Pa"
    assert estimate["r_squared"]["value"] == pytest.approx(1)
    with raises(PhysicsError, "too_little_data", match="nonzero"):
        analysis.estimate_reservoir_pressure([0, 1], [1, 2])


STATED = {"cp_hot": 4000, "cp_cold": 4000, "arrangement": "counterflow"}


def test_estimate_conductance_is_the_mean_duty_over_the_lmtd():
    """Equal terminal differences of 40 K give the duty over 40 K."""
    conductance = analysis.estimate_conductance(350, 340, 300, 310, 10, 10, **STATED)
    assert conductance["value"] == pytest.approx(10 * 4000 * 10 / 40)
    assert conductance["unit"] == "W/K"
    with raises(PhysicsError, "too_little_data", match="agree"):
        analysis.estimate_conductance(350, 340, 300, 340, 10, 10, **STATED)
    with raises(ValidationError, "unknown_name", match="arrangement"):
        analysis.estimate_conductance(
            350, 340, 300, 310, 10, 10, cp_hot=4000, cp_cold=4000, arrangement="cross"
        )


def test_estimate_conductance_needs_the_heat_capacities_and_the_arrangement():
    """Nothing is assumed about the fluid or the flow arrangement."""
    with pytest.raises(TypeError):
        analysis.estimate_conductance(350, 340, 300, 310, 10, 10)


def test_fits_take_units_for_what_has_a_quantity():
    """The offset and the pressure convert; the slope has no unit to convert."""
    fitted = analysis.fit_head_correction(
        [1e5, 2e5, 3e5], [3e5, 5e5, 7e5], units={"pressure": "bar"}
    )
    assert fitted["offset"]["unit"] == "bar" and fitted["slope"]["unit"] == "-"
    flows = np.array([0.01, 0.02, 0.04])
    estimate = analysis.estimate_reservoir_pressure(
        flows, 2e7 - 1e8 * flows, units={"pressure": "bar"}
    )
    assert estimate["pressure"]["value"] == pytest.approx(200.0)
    assert estimate["pressure"]["unit"] == "bar"
    conductance = analysis.estimate_conductance(
        350, 340, 300, 310, 10, 10, **STATED, units={"thermal_conductance": "W/K"}
    )
    assert conductance["unit"] == "W/K"
    with pytest.raises(ValidationError):
        analysis.fit_head_coefficients([1], [1], [1], 1, units={"powr": "kW"})
