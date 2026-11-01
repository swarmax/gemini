"""The levelised cost of a product and the annualised cost of a plant."""

from gemini.evaluate._utils.cost import annuity, investment, lifetime_cost, yearly_cost
from gemini.evaluate._utils.flows import Flows
from gemini.evaluate._utils.outcome import reported, unavailable
from gemini.run.assumptions import discounting
from gemini.types.shapes import measure


def levelised(plant, problem, results, product, discount, on_error):
    """Return the levelised cost of ``product`` ("heat" or "cold") over the lifetime."""
    return reported(
        on_error,
        "currency/J",
        lambda: _cost_of(problem.apply_site(plant), problem, results, product, discount, on_error),
    )


def _cost_of(plant, problem, results, product, discount, on_error):
    """Compute the levelised cost; ``on_error`` applies to a value the plant cannot give."""
    assumptions = problem.assumptions
    rate, years = discounting(assumptions, *discount)
    cost = investment(plant, assumptions, on_error)
    unit = "currency/J"
    if cost.value is None:
        return unavailable(unit, cost.reason, on_error)
    flows = Flows(plant, results)
    other = "cold" if product == "heat" else "heat"
    delivered = flows.energy(product)
    if delivered <= 0:
        return unavailable(unit, f"the run delivers no {product}", on_error)
    share = 1.0
    if flows.energy(other) > 0:
        if assumptions.heat_cost_share is None:
            reason = "the plant delivers heat and cold; the split of its cost is not defined"
            return unavailable(unit, reason, on_error)
        share = (
            assumptions.heat_cost_share if product == "heat" else 1 - assumptions.heat_cost_share
        )
    yearly = yearly_cost(plant, problem, results, "raise").value
    factor = annuity(rate, years)
    return measure(
        share * lifetime_cost(cost.value, yearly, factor) / (delivered * factor),
        unit,
        capex=measure(cost.value, cost.unit),
        opex=measure(yearly, "currency/yr"),
        energy=measure(delivered, "J/yr"),
        discount_rate=measure(rate, "-"),
        lifetime_years=measure(years, "yr"),
    )


def annualised(plant, problem, results, discount, on_error):
    """Return the annualised cost of a plant that already has its site."""
    assumptions = problem.assumptions
    rate, years = discounting(assumptions, *discount)
    cost = investment(plant, assumptions, on_error)
    unit = "currency/yr"
    if cost.value is None:
        return unavailable(unit, cost.reason, on_error)
    yearly = yearly_cost(plant, problem, results, "raise").value
    factor = annuity(rate, years)
    return measure(
        lifetime_cost(cost.value, yearly, factor) / factor,
        unit,
        capex=measure(cost.value, cost.unit),
        opex=measure(yearly, unit),
        annuity_factor=measure(factor, "yr"),
        discount_rate=measure(rate, "-"),
        lifetime_years=measure(years, "yr"),
    )
