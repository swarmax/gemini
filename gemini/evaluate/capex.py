"""Investment of a plant."""

from gemini.evaluate._utils.cost import investment
from gemini.evaluate._utils.outcome import reported


def capex(plant, problem, on_error="raise"):
    """Return the investment of a plant: the sum of the costs its modules declare.

    One implementation: ``gemini.types.cost.total_cost``. A module declares its cost by defining
    ``capex(assumptions)`` that returns a ``Cost`` from its own design values and the cost factors
    of ``problem.assumptions``. A factor without a value raises ``ValidationError`` (code
    ``missing_assumption``), and nothing is estimated. The design values are those of the plant
    with the site of the problem (``problem.apply_site``).

    Parameters
    ----------
    plant : Module
        The plant whose modules and descendants declare costs.
    problem : Problem
        Its assumptions give the cost factors, the ``currency`` and the ``cost_price_year``; its
        site gives design values.
    on_error : {"raise", "record"}, optional
        A value the inputs cannot give raises; ``"record"`` makes it ``None`` with a ``reason``.

    Returns
    -------
    Value
        A ``gm.units.Quantity`` in SI, with the parts of the result in ``parts`` (``to_plain``
        gives the JSON). ``{value, unit, price_year, source}`` as plain JSON. ``value`` is
        the investment in the
        currency of the costs (``unit``), with their ``price_year`` (a value in ``year``) and
        ``source``. Costs in different currencies or price years raise ``ValidationError``.
    """
    return reported(
        on_error,
        "currency",
        lambda: investment(problem.apply_site(plant), problem.assumptions, on_error),
    )
