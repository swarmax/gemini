"""One report of a finished run."""

from gemini._utils.jsonable import to_plain
from gemini.evaluate._utils.cost import equipment
from gemini.evaluate._utils.ratings import rating_of
from gemini.evaluate._utils.series import energy
from gemini.evaluate._utils.verdict import verdict
from gemini.evaluate.capacities import capacities
from gemini.evaluate.capex import capex
from gemini.evaluate.co2 import co2
from gemini.evaluate.constraints import constraints
from gemini.evaluate.lcoc import lcoc
from gemini.evaluate.lcoh import lcoh
from gemini.evaluate.lcts import lcts
from gemini.evaluate.opex import opex
from gemini.evaluate.totals import totals
from gemini.run._utils.apply import apply_case
from gemini.types.shapes import measure


class Report(dict):
    """The report of a run: a dict of the figures of ``report``, with ``to_dict`` for plain JSON."""

    def to_dict(self):
        """Return the report as plain JSON: every ``Quantity`` as ``{value, unit}``."""
        return to_plain(dict(self))


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
        else ``None``) and ``failed_steps`` (the number of steps that failed). ``to_dict()`` gives
        plain JSON.
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
    )


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
