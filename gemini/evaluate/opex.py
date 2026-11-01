"""Annual operating cost of a plant run."""

from gemini.evaluate._utils.cost import yearly_cost
from gemini.evaluate._utils.outcome import reported


def opex(plant, problem, results, on_error="raise"):
    """Return the annual operating cost of a plant run.

    The sum of the declared fixed cost [currency/year], the declared variable cost
    [currency/J] times the heat and cold delivered per year, the yearly bill of the grid
    electricity, the fuel, the waste and the chemicals, and the CO2 emitted per year at
    ``co2_price`` when the assumptions give it. The run is scaled to a year. A price along the
    demand is integrated over the run: the power of each step times its price.

    Parameters
    ----------
    plant : Module
        The plant whose modules declare costs; its design values are those with the site of the
        problem.
    problem : Problem
        Its assumptions give the prices, needed only for an energy that the run buys; a missing
        needed price raises ``ValidationError`` (code ``missing_assumption``). Co-produced gas
        costs nothing.
    results : Results
        A finished run of the plant.
    on_error : {"raise", "record"}, optional
        A value the inputs cannot give raises; ``"record"`` makes it ``None`` with a ``reason``.

    Returns
    -------
    Value
        A ``gm.units.Quantity`` in SI, with the parts of the result in ``parts`` (``to_plain``
        gives the JSON). ``{value, unit, components}`` with ``unit`` the cost currency per
        year and ``components``
        ``{fixed, variable, electricity, fuel, waste, chemical}`` and ``co2`` with a price for it,
        each a value in that unit. With no declared cost and ``on_error="record"``, ``value`` is
        ``None`` with a ``reason``, and only the bills are given. A currency in the assumptions
        other than the cost's raises ``ValidationError``.
    """
    return reported(
        on_error,
        "currency/yr",
        lambda: yearly_cost(problem.apply_site(plant), problem, results, on_error),
    )
