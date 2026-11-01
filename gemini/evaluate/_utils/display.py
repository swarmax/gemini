"""The unit in which a metric is shown in a table, and the conversion of a number to it."""

from gemini import units as _units
from gemini._utils.strings import close_matches, did_you_mean, join_names
from gemini.errors import ValidationError

DISPLAY = {
    "heat_delivered": ("energy", "MWh"),
    "cold_delivered": ("energy", "MWh"),
    "boiler_heat": ("energy", "MWh"),
    "electricity_bought": ("energy", "MWh"),
    "electricity_sold": ("energy", "MWh"),
    "gas_bought": ("energy", "MWh"),
    "peak_heat": ("power", "MW"),
    "peak_cold": ("power", "MW"),
    "capex": ("money", "MEUR"),
    "opex": ("annual_money", "MEUR/yr"),
    "annualised_cost": ("annual_money", "MEUR/yr"),
    "lcts": ("money_per_energy", "EUR/MWh"),
    "lcoh": ("money_per_energy", "EUR/MWh"),
    "lcoc": ("money_per_energy", "EUR/MWh"),
    "co2": ("mass", "kt"),
    "co2_emitted": ("mass", "kt"),
    "methane_emitted": ("mass", "kt"),
}
"""For each metric its quantity and the unit it is shown in; a metric not listed is shown in SI."""


def display_units(metrics, units=None):
    """Return ``{metric: unit}`` for the metrics that have a display unit; others are left out.

    Parameters
    ----------
    metrics : list of str
        The metrics of a table.
    units : dict, optional
        ``{metric: unit}`` that replaces the display unit of a metric. A name that is not in
        ``metrics`` or has no display unit raises ``invalid_value``; a unit that is unknown or
        of another dimension than the metric raises ``invalid_unit``.

    Returns
    -------
    dict
        The unit of each metric of ``metrics`` that is shown in a unit.
    """
    chosen = {name: DISPLAY[name][1] for name in metrics if name in DISPLAY}
    for name, unit in (units or {}).items():
        if name not in chosen:
            raise ValidationError(
                f"units.{name}; expected one of {join_names(chosen)}"
                f"{did_you_mean(name, chosen)}",
                path=f"units.{name}",
                code="invalid_value",
                suggestions=close_matches(name, chosen),
            )
        _units.convert(1.0, _units.si_unit(chosen[name]), unit, DISPLAY[name][0])
        chosen[name] = unit
    return chosen


def in_unit(metric, number, unit):
    """Return ``number`` in SI of the metric ``metric`` converted to ``unit``; ``None`` stays."""
    if number is None:
        return None
    quantity, default = DISPLAY[metric]
    return _units.convert(number, _units.si_unit(default), unit, quantity)
