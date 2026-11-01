"""The unit in which a metric is shown in a table, and the conversion of a number to it."""

from collections.abc import Mapping

from gemini import units as _units
from gemini._utils.strings import close_matches, did_you_mean, join_names
from gemini.errors import ValidationError
from gemini.types.shapes import Value

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
    "annual_energy": ("annual_energy", "MWh/yr"),
    "duration": ("duration", "d"),
    "co2": ("mass", "kt"),
    "co2_emitted": ("mass", "kt"),
    "methane_emitted": ("mass", "kt"),
    "permeability": ("permeability", "mD"),
    "temperature_gradient": ("temperature_gradient", "K/km"),
    "price_per_mass": ("money_per_mass", "EUR/t"),
    "flow": ("volume_flow", "m3/h"),
    "temperature": ("temperature", "degC"),
}
"""For each metric its quantity and the unit it is shown in; a metric not listed is shown in SI.

The values of a case that a study moves (permeability, gradient, prices) are shown by the unit of
their SI unit (``by_si_unit``), through the entries named after their quantity.

The one display table of ``gm.evaluate``: ``flow`` and ``temperature`` stand for the quantities of
the capacities and constraints of a report, which are shown by their SI unit (``by_si_unit``).
"""


def by_si_unit():
    """Return ``{SI unit: display unit}`` derived from ``DISPLAY``: ``J`` shows in ``MWh``."""
    return {_units.si_unit(unit): unit for _, unit in DISPLAY.values()}


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


def shown(found, table):
    """Return ``found`` with every ``Quantity`` in it converted by ``table``, ``{SI unit: unit}``.

    Mappings and lists are walked, and so are the parts of a ``Value``; a quantity whose SI unit
    is not in the table, and anything that is not a quantity, stays as it is.
    """
    if isinstance(found, _units.Quantity):
        target = table.get(_units.si_unit(str(found.unit)))
        converted = found if target is None else found.to(target)
        if isinstance(found, Value):
            return Value(converted.value, converted.unit, found.reason, shown(found.parts, table))
        return converted
    if isinstance(found, Mapping):
        return {key: shown(item, table) for key, item in found.items()}
    if isinstance(found, (list, tuple)):
        return [shown(item, table) for item in found]
    return found
