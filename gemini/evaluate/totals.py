"""The plant KPIs under fixed names and the totals at the edge: ``gm.evaluate``.

Every KPI is read from the columns of a finished run (``results.to_frame()``): the totals come from
the ports of the edge modules, so nothing is summed over the plant. A tick where a needed
column has no value (a skipped or failed row) is left out of that sum or peak.
"""

from dataclasses import dataclass
from functools import partial
from typing import Any

import numpy as np

from gemini.evaluate._utils.series import (
    COLD_DELIVERED,
    HEAT_DELIVERED,
    energy,
    leaf_total,
    port_difference,
    useful_cold,
    useful_heat,
)
from gemini.modules.environment import Atmosphere, Formation
from gemini.modules.grids import (
    ChemicalGrid,
    CoolingGrid,
    ElectricityGrid,
    GasGrid,
    HeatingGrid,
    WasteGrid,
)
from gemini.types.shapes import measure

__all__ = ["KPI_NAMES", "totals"]


@dataclass(frozen=True)
class _Series:
    """The plant-level power series [W] the KPIs share, each ``None`` when the plant lacks it."""

    seconds: np.ndarray
    heat: Any
    heat_unmet: Any
    cold: Any
    cold_unmet: Any
    electricity: Any


def _read(plant, results):
    """Return the shared series of a run."""
    frame = results.to_frame()
    sensible = leaf_total(plant, frame, "unmet_sensible", CoolingGrid)
    latent = leaf_total(plant, frame, "unmet_latent", CoolingGrid)
    return _Series(
        seconds=results.durations,
        heat=useful_heat(plant, frame),
        heat_unmet=leaf_total(plant, frame, "unmet_demand", HeatingGrid),
        cold=useful_cold(plant, frame),
        cold_unmet=None if sensible is None or latent is None else sensible + latent,
        electricity=leaf_total(plant, frame, "power_out", ElectricityGrid),
    )


def _coverage(series, delivered, unmet, consumer):
    """Return delivered energy over demanded energy, or a reason when it is undefined."""
    delivered, unmet = getattr(series, delivered), getattr(series, unmet)
    if delivered is None or unmet is None:
        return None, f"the plant has no {consumer}"
    demand = delivered + unmet
    demanded = energy(demand, series.seconds)
    if demanded <= 0:
        return None, "the demand is zero over the window"
    return energy(delivered.where(demand.notna()), series.seconds) / demanded, None


def _peak(series, delivered, consumer):
    """Return the largest delivered power, or a reason when there is none."""
    delivered = getattr(series, delivered)
    if delivered is None:
        return None, f"the plant has no {consumer}"
    if delivered.notna().sum() == 0:
        return None, "no tick has a delivered power"
    return float(delivered.max()), None


def _cop(series):
    if series.heat is None:
        return None, "the plant has no HeatingGrid"
    if series.electricity is None:
        return None, "the plant has no ElectricityGrid"
    consumed = energy(series.electricity.where(series.heat.notna()), series.seconds)
    if consumed <= 0:
        return None, "no electricity is consumed over the window"
    return energy(series.heat.where(series.electricity.notna()), series.seconds) / consumed, None


_KPIS = {
    "heating_coverage": (
        "-",
        partial(_coverage, delivered="heat", unmet="heat_unmet", consumer="HeatingGrid"),
    ),
    "cooling_coverage": (
        "-",
        partial(_coverage, delivered="cold", unmet="cold_unmet", consumer="CoolingGrid"),
    ),
    "cop": ("-", _cop),
    "peak_heat": ("W", partial(_peak, delivered="heat", consumer="HeatingGrid")),
    "peak_cold": ("W", partial(_peak, delivered="cold", consumer="CoolingGrid")),
}
"""Each KPI name with its unit and the function that computes ``(value, reason)``."""


KPI_NAMES = tuple(_KPIS)
"""The names of the KPIs among the totals."""


def _kpis(plant, results):
    """Return the KPIs of a finished run as ``{name: {value, unit}}``; see ``totals``."""
    series = _read(plant, results)
    values = {}
    for name, (unit, compute) in _KPIS.items():
        number, reason = compute(series)
        values[name] = measure(number, unit, reason)
    return values


_EDGE_TOTALS = {
    "electricity_bought": ("J", ElectricityGrid, "net_import"),
    "electricity_sold": ("J", ElectricityGrid, "net_export"),
    "gas_bought": ("J", GasGrid, "gas_out.chemical_flow"),
    "co2_emitted": ("kg", Atmosphere, "co2_emission"),
    "methane_emitted": ("kg", Atmosphere, "methane_emission"),
    "waste": ("kg", WasteGrid, "waste_in.mass_flow"),
    "chemicals": ("kg", ChemicalGrid, "chemical_out.mass_flow"),
}
"""Each total read from one column of the edge modules: unit, module class and column."""


def _integral(series, seconds, unit):
    """Return the integral of ``series`` over a run, or ``None`` with what it needs."""
    if series is None:
        return measure(None, unit, "the plant has no module at its edge that shows it")
    return measure(energy(series, seconds), unit)


def totals(plant, case, results):
    """Return what crossed the plant's edge over a run, read from the edge modules' ports.

    Parameters
    ----------
    plant : Module
        The plant that produced ``results``.
    case : Case
        The case of the run; the totals do not read it.
    results : Results
        A finished ``simulate`` or ``replay``.

    Returns
    -------
    dict
        ``{name: Value}``, each a ``gm.units.Quantity`` in SI (``to_plain`` gives the JSON):
        ``heat_delivered``, ``cold_delivered``, what the water
        gave the users; ``heat_useful``, ``cold_useful``, the part of it up to their demand;
        ``heat_surplus``, ``cold_surplus``, the rest; ``electricity_bought``,
        ``electricity_sold``, ``gas_bought`` (lower heating value) and ``losses`` in J,
        ``co2_emitted``, ``methane_emitted``, ``waste`` and ``chemicals`` in kg.
        ``losses`` is the net heat into the ``Atmosphere`` and the ``Formation``. A value is
        ``None``, with a ``reason``, when no module at the edge shows it.

        The KPIs follow, with E(x) = sum over ticks of x * tick duration [J]:

        - ``heating_coverage`` [-] = E(heat delivered) / E(heat delivered + unmet_demand) summed
          over the plant's ``HeatingGrid`` leaves: the share of the demanded heat delivered.
        - ``cooling_coverage`` [-] = E(cold delivered) / E(cold delivered + unmet_sensible +
          unmet_latent) over the ``CoolingGrid`` leaves.
        - ``cop`` [-] = E(heat delivered) / E(``ElectricityGrid.power_out``): heat delivered per
          unit of electricity consumed. Cooling is not counted.
        - ``peak_heat``, ``peak_cold`` [W] = the largest tick sum of heat or cold delivered over
          the grid leaves (delivered power, not the demand peak).

        A plant without a consumer leaf, for example the doublet heat plant, gives ``None`` for
        the KPIs that need one.
    """
    frame = results.to_frame()
    seconds = results.durations
    report = {
        "heat_delivered": _integral(port_difference(plant, frame, *HEAT_DELIVERED), seconds, "J"),
        "heat_useful": _integral(useful_heat(plant, frame), seconds, "J"),
        "heat_surplus": _integral(leaf_total(plant, frame, "surplus", HeatingGrid), seconds, "J"),
        "cold_delivered": _integral(port_difference(plant, frame, *COLD_DELIVERED), seconds, "J"),
        "cold_useful": _integral(useful_cold(plant, frame), seconds, "J"),
        "cold_surplus": _integral(leaf_total(plant, frame, "surplus", CoolingGrid), seconds, "J"),
    }
    for name, (unit, module_class, field) in _EDGE_TOTALS.items():
        report[name] = _integral(leaf_total(plant, frame, field, module_class), seconds, unit)
    air = leaf_total(plant, frame, "heat_in", Atmosphere)
    ground = leaf_total(plant, frame, "heat_in", Formation)
    known = [series for series in (air, ground) if series is not None]
    report["losses"] = _integral(sum(known) if known else None, seconds, "J")
    return report | _kpis(plant, results)
