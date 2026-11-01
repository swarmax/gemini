"""Investment and yearly cost of a plant run, before the site and the error policy of a caller."""

from gemini.errors import ValidationError
from gemini.evaluate._utils.flows import Flows
from gemini.evaluate._utils.outcome import unavailable
from gemini.evaluate.co2 import co2
from gemini.types.cost import total_cost
from gemini.types.shapes import measure
from gemini.units import SECONDS_PER_YEAR

NO_COST = (
    "no module declares a cost: a module declares it by defining capex(assumptions) that returns "
    "a Cost"
)
"""The reason when a plant has no declared cost."""

BILLED = ("electricity", "fuel", "waste", "chemical")
"""The flows that are bought or discarded, each with a bill of its name."""


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


def investment(plant, assumptions, on_error):
    """Return the investment as ``capex`` does, for a plant that already has its site."""
    cost = total_cost(plant, assumptions)
    if cost is None:
        return unavailable("currency", NO_COST, on_error)
    year = measure(cost.price_year, "-")
    return measure(cost.capex, "currency", price_year=year, source=cost.source)


def _components(amounts, unit):
    """Return each amount of a cost as a value."""
    return {name: measure(amount, unit) for name, amount in amounts.items()}


def _bills(flows, problem, results, plant):
    """Return the yearly bills of what the plant buys and discards, and of its CO2 when priced."""
    bills = {name: flows.cost(name, problem) for name in BILLED}
    price = problem.assumptions.co2_cost()
    if price is not None:
        emitted = co2(plant, problem, results)
        bills["co2"] = emitted.value * price * SECONDS_PER_YEAR / emitted.parts["window"].value
    return bills


def yearly_cost(plant, problem, results, on_error):
    """Return the annual operating cost as ``opex`` does, for a plant that already has its site."""
    assumptions = problem.assumptions
    cost = total_cost(plant, assumptions)
    flows = Flows(plant, results)
    bills = _bills(flows, problem, results, plant)
    if cost is None:
        unit = "currency/yr"
        return unavailable(unit, NO_COST, on_error, components=_components(bills, unit))
    if cost.currency != assumptions.currency:
        raise ValidationError(
            f"assumptions.currency = {assumptions.currency!r}; expected the cost currency "
            f"{cost.currency!r}",
            path="assumptions.currency",
        )
    components = {
        "fixed": cost.opex_fixed,
        "variable": cost.opex_variable * (flows.energy("heat") + flows.energy("cold")),
        **bills,
    }
    unit = "currency/yr"
    return measure(sum(components.values()), unit, components=_components(components, unit))
