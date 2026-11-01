"""Fits of model parameters to measurements: pump curves, reservoir pressure, exchanger UA.

Modules hold the parameters a fit produces; the fit itself lives here, on plain NumPy arrays or
through the physics functions.
"""

import numpy as np

from gemini import units as physics_units
from gemini.errors import PhysicsError, ValidationError
from gemini.physics import constants, heat_transfer
from gemini.types.shapes import OutputUnits, value

CURVE_COEFFICIENTS = 6
"""Number of ascending polynomial coefficients of an ESP curve, so at least so many flows."""


def fit_head_coefficients(flows, frequencies, heads, stage_count, units=None):
    """Fit the six ascending US-basis ESP head coefficients from SI observations.

    Parameters
    ----------
    flows, frequencies, heads : array_like
        Volume flows [m3/s], frequencies [Hz] and heads [Pa], at least six matching observations
        with six distinct flows.
    stage_count : int
        Number of pump stages, positive.
    units : dict, optional
        A map from quantity to unit, as on every ``gm.analysis`` return; the coefficients are on
        their own basis, so the map is only checked.

    Returns
    -------
    dict
        A value: the six coefficients of ``physics.pumps.head``, ascending, on their own mixed US
        basis (ft of head per stage at 60 Hz with flow in bbl/day), so the unit is ``"-"``.

    Notes
    -----
    Least-squares polynomial of degree five through the observations reduced to one stage at the
    reference frequency by the affinity law ``H ~ f^2``.
    """
    OutputUnits(units)
    q, f, h = (np.asarray(item, dtype=float) for item in (flows, frequencies, heads))
    if q.shape != f.shape or q.shape != h.shape or q.ndim != 1 or len(q) < CURVE_COEFFICIENTS:
        raise PhysicsError(
            "ESP: at least six matching observations required", code="too_little_data"
        )
    if stage_count <= 0 or np.any(f <= 0) or np.any(q < 0) or not np.isfinite([q, f, h]).all():
        raise PhysicsError(
            "ESP: fitting requires finite positive stages and frequencies", code="too_little_data"
        )
    x = physics_units.m3s_to_bbl_per_day(q)
    y = physics_units.pa_to_ft_head(h) / (
        stage_count * (f / constants.ESP_REFERENCE_FREQUENCY) ** 2
    )
    if len(np.unique(x)) < CURVE_COEFFICIENTS:
        raise PhysicsError("ESP: six distinct flow values are required", code="too_little_data")
    degree = CURVE_COEFFICIENTS - 1
    return value(np.polynomial.Polynomial.fit(x, y, degree).convert().coef.tolist(), "-")


def fit_head_correction(measured, theoretical, units=None):
    """Fit the affine correction ``theoretical = slope * measured + offset`` [-, Pa].

    Parameters
    ----------
    measured, theoretical : array_like
        Measured and theoretical heads [Pa], at least two finite pairs with distinct measurements.
    units : dict, optional
        A map from quantity to unit for the returned values.

    Returns
    -------
    dict
        ``{slope, offset}``: the least-squares slope [-] and offset [Pa], each a value.
    """
    output = OutputUnits(units)
    x, y = (np.asarray(item, dtype=float) for item in (measured, theoretical))
    if x.shape != y.shape or len(x) < 2 or not np.isfinite([x, y]).all() or np.var(x) == 0:
        raise PhysicsError(
            "ESP: two or more finite, distinct measurements required", code="too_little_data"
        )
    slope = np.sum((x - x.mean()) * (y - y.mean())) / np.sum((x - x.mean()) ** 2)
    offset = float(y.mean() - slope * x.mean())
    return {
        "slope": value(float(slope), "-"),
        "offset": output.value(offset, "Pa", "pressure_difference"),
    }


def estimate_reservoir_pressure(flows, bottomhole_pressures, units=None):
    """Fit the reservoir pressure [Pa] and the R-squared [-] from flow observations.

    Parameters
    ----------
    flows, bottomhole_pressures : array_like
        Volume flows [m3/s] and bottomhole pressures [Pa], at least two matching finite samples
        with nonzero flows.
    units : dict, optional
        A map from quantity to unit for the returned values.

    Returns
    -------
    dict
        ``{pressure, r_squared}``, each a value: the slope of the least-squares line ``p_bh / Q =
        p_res (1 / Q) + b``, which is the reservoir pressure of a linear inflow relation, and the
        R-squared of the line.
    """
    output = OutputUnits(units)
    q, p = (np.asarray(item, dtype=float) for item in (flows, bottomhole_pressures))
    if (
        q.shape != p.shape
        or q.ndim != 1
        or len(q) < 2
        or np.any(q == 0)
        or not np.isfinite([q, p]).all()
    ):
        raise PhysicsError(
            "Reservoir pressure estimation needs at least two matching finite, nonzero samples",
            code="too_little_data",
        )
    x, y = 1 / q, p / q
    if np.ptp(x) == 0 or np.ptp(y) == 0:
        raise PhysicsError(
            "Reservoir pressure regression requires variation", code="too_little_data"
        )
    coefficients = np.polyfit(x, y, 1)
    residual = y - np.poly1d(coefficients)(x)
    r_squared = 1 - np.sum(residual**2) / np.sum((y - np.mean(y)) ** 2)
    return {
        "pressure": output.value(float(coefficients[0]), "Pa", "pressure"),
        "r_squared": value(float(r_squared), "-"),
    }


def estimate_conductance(
    hot_in_T,
    hot_out_T,
    cold_in_T,
    cold_out_T,
    m_dot_hot,
    m_dot_cold,
    *,
    cp_hot,
    cp_cold,
    arrangement,
    units=None,
):
    """Return the apparent UA of an exchanger as a value in W/K, from temperatures and mass flows.

    Temperatures are in K, mass flows in kg/s and heat capacities in J/kg/K. Raises
    ``PhysicsError`` when the measurements cannot determine UA: a stopped stream, hot and
    cold duties that disagree by more than 5 %, or no positive LMTD; see
    ``heat_transfer.apparent_conductance``. ``units`` is a map from quantity to unit.
    """
    output = OutputUnits(units)
    if arrangement not in {"counterflow", "parallel"}:
        raise ValidationError(
            f"HeatExchanger: unknown arrangement {arrangement!r}; expected counterflow or parallel",
            code="unknown_name",
        )
    apparent, code, hot_duty, cold_duty, delta = heat_transfer.apparent_conductance(
        arrangement,
        hot_in_T,
        hot_out_T,
        cold_in_T,
        cold_out_T,
        m_dot_hot,
        m_dot_cold,
        cp_hot,
        cp_cold,
    )
    if code == heat_transfer.NONPOSITIVE_INPUT:
        raise PhysicsError(
            "HeatExchanger: mass flows and heat capacities must be positive", code="too_little_data"
        )
    if code == heat_transfer.DISAGREEING_DUTIES:
        raise PhysicsError(
            f"HeatExchanger: hot/cold duties must agree within 5%; got {hot_duty} W and "
            f"{cold_duty} W",
            code="too_little_data",
        )
    if code == heat_transfer.NO_LMTD:
        raise PhysicsError(
            f"HeatExchanger: positive LMTD required; got {delta} K", code="too_little_data"
        )
    return output.value(apparent, "W/K", "thermal_conductance")
