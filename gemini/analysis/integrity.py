"""Well integrity: corrosion forecast and the calibration and erosion entry points."""

from datetime import timedelta

import numpy as np

from gemini import units as physics_units
from gemini._utils.strings import close_matches, did_you_mean, join_names
from gemini._utils.time import to_utc
from gemini.errors import NotImplementedYet, ValidationError
from gemini.physics import corrosion
from gemini.types.shapes import OutputUnits, value

_CONDITIONS = {
    "temperature": ("K", "temperature"),
    "pressure": ("Pa", "pressure"),
    "water_flow_rate": ("m3/s", "volume_flow"),
    "co2_partial_pressure": ("Pa", "pressure"),
    "co2_fraction": (None, None),
    "water_density": ("kg/m3", "density"),
    "water_viscosity": ("Pa.s", "viscosity"),
    "diameter": ("m", "length"),
    "roughness": ("m", "length"),
    "bicarb_concentration": ("kg/m3", "mass_concentration"),
    "ionic_strength": ("kg/m3", "mass_concentration"),
}
"""The conditions of ``co2_corrosion_rate`` a model may state, with SI unit and quantity."""


def _conditions(model):
    """Return the model's conditions in SI, rejecting names ``co2_corrosion_rate`` lacks."""
    given = model.get("conditions", {})
    unknown = sorted(set(given) - set(_CONDITIONS))
    if unknown:
        raise ValidationError(
            f"corrosion_forecast: model.conditions.{unknown[0]} is unknown; expected one of "
            f"{join_names(_CONDITIONS)}{did_you_mean(unknown[0], _CONDITIONS)}",
            path=f"conditions.{unknown[0]}",
            suggestions=close_matches(unknown[0], _CONDITIONS),
        )
    return {name: _si(name, value) for name, value in given.items()}


def _si(name, value):
    """Return one condition in SI, converting a ``Quantity``."""
    unit, quantity = _CONDITIONS[name]
    return physics_units.value_in_si(value, unit, f"model.conditions.{name}", quantity)


def _times(start, end):
    """Return the forecast instants: the start, each whole year after it, and the end."""
    times = [start]
    while (
        next_year := start + timedelta(seconds=len(times) * physics_units.SECONDS_PER_YEAR)
    ) < end:
        times.append(next_year)
    return times + [end]


def corrosion_forecast(model, until, units=None):
    """Return the wall thickness over time and the years left of a corroding wall.

    The penetration rate is constant: ``co2_corrosion_rate`` of the model's correlation at its
    conditions. The wall loss is that rate integrated over time (``wall_loss``) and the time to
    the minimum wall is the linear extrapolation of ``time_to_minimum_wall``.

    Parameters
    ----------
    model : dict
        ``correlation`` (``"NORSOK"``, ``"DLM"`` or ``"DLD"``), ``conditions``, ``thickness`` [m]
        and ``minimum_thickness`` [m] of the wall at ``start``, and ``start`` (ISO 8601 UTC text
        or a datetime). ``conditions`` has the keyword arguments of ``co2_corrosion_rate`` with
        SI values or ``Quantity`` values: ``temperature`` [K], ``pressure`` [Pa],
        ``water_flow_rate`` [m3/s] and ``co2_partial_pressure`` [Pa] or ``co2_fraction`` [-], and
        optionally ``water_density`` [kg/m3], ``water_viscosity`` [Pa.s], ``diameter`` and
        ``roughness`` [m],
        ``bicarb_concentration`` and ``ionic_strength`` [kg/m3].
    until : str or datetime
        End of the forecast, after ``start``.
    units : dict, optional
        A map from quantity to unit for the thickness; ``rate`` stays in mm/year, the literature
        unit of the correlations, and ``years_left`` in years.

    Returns
    -------
    dict
        Plain JSON ``{correlation, rate, thickness, minimum_thickness, years_left}``. ``rate`` is
        the penetration rate [mm/year], a value; ``thickness`` is the time series of the wall [m]
        at the start, each whole year after it and ``until`` (a breached wall is not clipped);
        ``years_left`` [year] is a value: the time from ``start`` to the minimum wall, 0 when the
        wall is already at it, and ``None`` with a ``reason`` when the rate is not positive. The
        rate of a correlation outside its domain raises
        ``PhysicsError``.
    """
    output = OutputUnits(units)
    start, end = to_utc(model["start"]), to_utc(until)
    if end <= start:
        raise ValidationError(
            f"corrosion_forecast: until = {end.isoformat()}; expected a time after the start "
            f"{start.isoformat()}",
            path="until",
        )
    rate = corrosion.co2_corrosion_rate(model["correlation"], **_conditions(model))
    times = _times(start, end)
    seconds = np.diff([time.timestamp() for time in times])
    loss = corrosion.wall_loss([rate] * len(seconds), seconds)
    thickness = model["thickness"] - np.concatenate([[0.0], loss]) / 1000
    remaining = corrosion.time_to_minimum_wall(
        model["thickness"], model["minimum_thickness"], rate / 1000 / physics_units.SECONDS_PER_YEAR
    )
    left = value(None, "yr", "the corrosion rate is not positive")
    if rate > 0:
        left = value(remaining / physics_units.SECONDS_PER_YEAR, "yr")
    return {
        "correlation": model["correlation"],
        "rate": value(rate, "mm/year"),
        "thickness": output.series(times, thickness, "m", "length"),
        "minimum_thickness": output.value(model["minimum_thickness"], "m", "length"),
        "years_left": left,
    }


def calibrate_corrosion(logs):
    """Return the corrosion model fitted to wall-thickness logs.

    Parameters
    ----------
    logs : list of dict
        Caliper or ultrasonic logs ``{time, thickness}`` of one tubing joint, with ``time`` as ISO
        8601 UTC text and ``thickness`` [m], oldest first.

    Returns
    -------
    dict
        Plain JSON ``corrosion_forecast``'s ``model``: the correlation and its fitted
        coefficients, the conditions and the last measured ``thickness`` and ``start``.

    Raises
    ------
    NotImplementedYet
        Always: the fit of the correlation constants to logs is not built yet.
    """
    raise NotImplementedYet("analysis.calibrate_corrosion")


def erosion(plant, well, units=None):
    """Return the erosion wear of the pump and the tubing of a production well.

    Parameters
    ----------
    plant : Module
        A plant with parameter values.
    well : str
        Dotted path of the production well chain, as for ``nodal``.
    units : dict, optional
        A map from quantity to unit for the returned values.

    Returns
    -------
    dict
        Plain JSON with the DNV RP O501 penetration rate [mm/year] of the pump and of each tubing
        section and the API RP 14E velocity margin [m/s].

    Raises
    ------
    NotImplementedYet
        Always: the correlations exist (``erosion_rate``), but a plant holds neither the flow
        nor the solids content they need, and the retained model has no solids fraction.
    """
    raise NotImplementedYet("analysis.erosion")
