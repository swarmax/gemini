"""One report of a finished run."""

import json

from gemini._utils.jsonable import to_plain
from gemini.evaluate._utils.cost import equipment
from gemini.evaluate._utils.display import DISPLAY, by_si_unit, display_units, shown
from gemini.evaluate._utils.ratings import rating_of
from gemini.evaluate._utils.series import energy
from gemini.evaluate._utils.verdict import verdict
from gemini.evaluate.capacities import capacities
from gemini.evaluate.capex import capex
from gemini.evaluate.co2 import co2
from gemini.evaluate.constraints import constraints
from gemini.evaluate.failures import failures
from gemini.evaluate.lcoc import lcoc
from gemini.evaluate.lcoh import lcoh
from gemini.evaluate.lcts import lcts
from gemini.evaluate.opex import opex
from gemini.evaluate.totals import totals
from gemini.run._utils.apply import apply_case
from gemini.types.shapes import measure
from gemini.units import si_unit


class Report(dict):
    """The report of a run: a dict of the figures of ``report``, with ``to_dict`` for plain JSON."""

    def to_dict(self, units=None):
        """Return the report as plain JSON in display units: every ``Quantity`` as ``{value, unit}``.

        The values inside the report stay SI; the dict shows them in the display table of
        ``gm.evaluate`` (energy in MWh, power in MW, money in MEUR, LCTS in EUR/MWh, CO2 in kt,
        flow in m3/h, temperature in degC), also inside ``capacities`` and ``constraints``.

        Parameters
        ----------
        units : dict, optional
            ``{metric: unit}`` that replaces the display unit of a metric of the report, and of the
            parts of that metric. A name that is not a metric with a display unit raises
            ``invalid_value``; a unit of another dimension raises ``invalid_unit``.
        """
        chosen = display_units(list(self), units)
        base = by_si_unit()
        return to_plain(
            {
                name: (
                    shown(item, base | {si_unit(DISPLAY[name][1]): chosen[name]})
                    if name in chosen
                    else shown(item, base)
                )
                for name, item in self.items()
            }
        )

    def __str__(self):
        """Return the report as the JSON text of ``to_dict()``."""
        return json.dumps(self.to_dict(), indent=2)


def report(plant, case, results):
    """Return the energy, capacities, costs, CO2, constraints and failed steps of a finished run.

    The costs are read with ``on_error="record"``: a cost that the case or the plant cannot give is
    a value ``None`` with a ``reason``, so that reports of many designs stay comparable.

    Parameters
    ----------
    plant : Module
        The plant of the run.
    case : Case
        The case of the run.
    results : Results
        A finished run.

    Returns
    -------
    Report
        A dict with ``heat_delivered``, ``cold_delivered``, ``boiler_heat``,
        ``electricity_bought`` and ``gas_bought`` (J over the run, ``Quantity`` values;
        ``boiler_heat`` is the heat of the boilers), ``capacities`` (see ``capacities``), ``capex``,
        ``opex``, ``lcts``, ``lcoh``, ``lcoc`` and ``co2`` (values; ``capex`` and ``opex`` keep
        their parts, per module and per kind), ``constraints`` (the list of ``constraints``),
        ``passed`` (``False`` if any constraint failed, ``True`` if none failed and one passed,
        else ``None``), ``failed_steps`` (the number of steps that failed), ``failures`` (the failed and skipped
        rows grouped by module path and code, see ``failures``; empty when nothing failed) and
        ``services`` (the
        services the case asks for, ``"heating"`` and ``"cooling"``, which ``compare`` needs to
        see that a design delivers them). ``to_dict(units=None)`` gives plain JSON in display units.
    """
    edge = totals(plant, case, results)
    checks = constraints(plant, case, results)
    return Report(
        heat_delivered=edge["heat_delivered"],
        cold_delivered=edge["cold_delivered"],
        boiler_heat=_boiler_heat(apply_case(plant, case), results),
        electricity_bought=edge["electricity_bought"],
        gas_bought=edge["gas_bought"],
        capacities=capacities(plant, case, results),
        capex=capex(plant, case, "record"),
        opex=opex(plant, case, results, "record"),
        lcts=lcts(plant, case, results, on_error="record"),
        lcoh=lcoh(plant, case, results, on_error="record"),
        lcoc=lcoc(plant, case, results, on_error="record"),
        co2=co2(plant, case, results, "record"),
        constraints=checks,
        passed=verdict([item["passed"] for item in checks]),
        failed_steps=len(results.errors()),
        failures=failures(results),
        services=_services(case),
    )


def _services(case):
    """Return the services that the demand of the case asks for."""
    if case.demand is None:
        return []
    return [name for name in ("heating", "cooling") if getattr(case.demand, name) is not None]


def _boiler_heat(plant, results):
    """Return the heat [J] that the boilers of ``plant`` gave over the run, as a value."""
    frame = results.to_frame()
    boilers = [
        (path, module)
        for path, module in equipment(plant).items()
        if module.equipment_kind in ("boiler", "electric_boiler")
    ]
    if not boilers:
        return measure(None, "J", "the plant has no boiler")
    powers = [rating_of(module).use(frame, path) for path, module in boilers]
    shown = [power for power in powers if power is not None]
    if not shown:
        return measure(None, "J", "the run shows no use of the boilers")
    return measure(sum(energy(power, results.durations) for power in shown), "J")
