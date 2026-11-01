"""Levelised cost of thermal supply."""

from gemini.evaluate._utils.flows import Flows
from gemini.evaluate._utils.levelised import annualised
from gemini.evaluate._utils.outcome import reported, unavailable
from gemini.run._utils.apply import apply_case
from gemini.types.shapes import measure


def lcts(plant, case, results, discount_rate=None, lifetime=None, on_error="raise"):
    """Return the levelised cost of thermal supply [currency/J].

    ``annualised_cost / (heat + cold)``, the heat and the cold delivered per year as scaled from
    the run. One cost over both products, so it needs no ``heat_cost_share``. The parameters are
    those of ``annualised_cost``.

    Returns
    -------
    Value
        A ``gm.units.Quantity`` in SI, with the parts of the result in ``parts`` (``to_plain``
        gives the JSON). ``{value, unit, annualised_cost, heat, cold}``, the last three each
        a value, ``heat`` and
        ``cold`` in J/year; ``value`` in currency/J (``.to("EUR/MWh")`` converts). A plant
        without equipment with a cost, or a run that delivers neither heat nor cold, has no value.
    """
    return reported(
        on_error,
        "currency/J",
        lambda: _lcts(plant, case, results, (discount_rate, lifetime), on_error),
    )


def _lcts(plant, case, results, discount, on_error):
    """Return the cost per joule of heat and cold; ``on_error`` applies to a missing value."""
    unit = "currency/J"
    sited = apply_case(plant, case)
    flows = Flows(sited, results)
    heat, cold = flows.energy("heat"), flows.energy("cold")
    if heat + cold <= 0:
        return unavailable(unit, "the run delivers neither heat nor cold", on_error)
    cost = annualised(sited, case, results, discount, on_error)
    if cost.value is None:
        return unavailable(unit, cost.reason, on_error)
    return measure(
        cost.value / (heat + cold),
        unit,
        annualised_cost=measure(cost.value, cost.unit),
        heat=measure(heat, "J/yr"),
        cold=measure(cold, "J/yr"),
    )
