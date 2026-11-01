"""Investment and yearly cost of a plant run, before the case and the error policy of a caller."""

import numpy as np

from gemini.case._utils.access import require
from gemini.evaluate._utils.co2_steps import emitted_steps
from gemini.evaluate._utils.flows import Flows
from gemini.evaluate._utils.level import level
from gemini.evaluate._utils.outcome import unavailable
from gemini.types.shapes import measure
from gemini.units import SECONDS_PER_YEAR

NO_COST = (
    "no module of the plant is equipment with a cost: a module declares it with an "
    "equipment_kind and a capex(finance)"
)
"""The reason when a plant has no equipment with a cost."""

BILLED = ("electricity", "fuel", "waste", "chemical")
"""The flows that are bought or discarded, each with a bill of its name."""

FINANCE = "assumptions.finance"
"""The path of the finance section in a case."""


def annuity(rate, years):
    """Return the sum of ``1 / (1 + rate) ** t`` for the years ``t = 1 .. years``."""
    if rate == 0:
        return float(years)
    return (1 - (1 + rate) ** -years) / rate


def lifetime_cost(investment, yearly, factor):
    """Return the discounted cost of a lifetime: ``capex + opex * A``.

    Over ``A`` it is the annualised cost ``capex / A + opex``; ``lcoh`` and ``lcoc`` divide it by
    ``energy * A`` in one step, so their numbers stay those of that order of operations.
    """
    return investment + yearly * factor


def equipment(plant):
    """Return ``{path: module}`` of the modules of ``plant`` that are equipment with a kind."""
    return {
        path: module
        for path, module in plant.named_modules()
        if getattr(module, "equipment_kind", None) is not None
    }


def investment(plant, case, on_error):
    """Return the investment as ``capex`` does, for a plant that already has its design values."""
    finance = require(case, FINANCE)
    units = equipment(plant)
    if not units:
        return unavailable("currency", NO_COST, on_error)
    items = {
        path: measure(module.capex(finance), "currency", kind=module.equipment_kind)
        for path, module in units.items()
    }
    parts = {"modules": items}
    if finance.price_year is not None:
        parts["price_year"] = measure(finance.price_year, "-")
    return measure(sum(item.value for item in items.values()), "currency", **parts)


def fixed_opex(plant, case):
    """Return the fixed opex of a year [currency/yr] of each kind of equipment of ``plant``."""
    finance = require(case, FINANCE)
    amounts = {}
    for module in equipment(plant).values():
        kind = module.equipment_kind
        amounts[kind] = amounts.get(kind, 0.0) + module.fixed_opex(finance)
    return amounts


def _bills(flows, case, results, plant):
    """Return the yearly bills of what the plant buys and discards, and of its CO2 when priced."""
    bills = {name: flows.cost(name, case) for name in BILLED}
    opex = require(case, FINANCE).opex
    if opex is not None and opex.co2 is not None:
        steps = emitted_steps(plant, case, results)
        price = level(case, f"{FINANCE}.opex.co2", len(steps))
        bills["co2"] = float(np.sum(steps * price)) * SECONDS_PER_YEAR / results.durations.sum()
    return bills


def _components(amounts, unit):
    """Return each amount of a cost as a value."""
    return {name: measure(amount, unit) for name, amount in amounts.items()}


def yearly_cost(plant, case, results, on_error):
    """Return the annual operating cost as ``opex`` does, for a plant with its design values."""
    flows = Flows(plant, results)
    bills = _bills(flows, case, results, plant)
    unit = "currency/yr"
    if not equipment(plant):
        return unavailable(unit, NO_COST, on_error, components=_components(bills, unit))
    by_kind = fixed_opex(plant, case)
    components = {"fixed": sum(by_kind.values()), **bills}
    return measure(
        sum(components.values()),
        unit,
        components=_components(components, unit),
        fixed_by_kind=_components(by_kind, unit),
    )
