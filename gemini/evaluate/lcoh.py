"""Levelised cost of heat."""

from gemini.evaluate._utils.levelised import levelised


def lcoh(plant, problem, results, discount_rate=None, lifetime=None, on_error="raise"):
    """Return the levelised cost of heat [currency/J]: the discounted cost over the discounted heat.

    ``(capex + opex * A) / (heat * A)`` with ``A`` the annuity factor, the sum over the lifetime
    years of ``1 / (1 + discount_rate) ** t``. ``capex`` and ``opex`` are the ``capex`` and
    ``opex`` of this package, ``opex`` and ``heat`` are per year as scaled from the run,
    constant over the lifetime, with no degradation, replacement or residual value. The whole
    plant cost is charged to the heat; for a plant that also delivers cold,
    ``problem.assumptions.heat_cost_share`` of it, and without that share it gives no value.

    Parameters
    ----------
    plant : Module
        The plant of the run.
    problem : Problem
        Its assumptions give the prices and, when not given below, the rate and lifetime; a rate
        or lifetime given nowhere raises ``ValidationError`` (code ``missing_assumption``).
    results : Results
        The finished run of the plant.
    discount_rate : float, optional
        Real discount rate per year [-]; ``assumptions.discount_rate`` when ``None``.
    lifetime : int, optional
        Years of operation; ``assumptions.lifetime_years`` when ``None``.
    on_error : {"raise", "record"}, optional
        A value the inputs cannot give raises; ``"record"`` makes it ``None`` with a ``reason``.

    Returns
    -------
    Value
        A ``gm.units.Quantity`` in SI, with the parts of the result in ``parts`` (``to_plain``
        gives the JSON). ``{value, unit, capex, opex, energy, discount_rate,
        lifetime_years}``, the last five each
        a value; ``value`` in currency/J (``.to("EUR/MWh")`` converts). A plant that
        declares no cost, delivers no heat, or also delivers cold without a ``heat_cost_share`` has
        no value.
    """
    return levelised(plant, problem, results, "heat", (discount_rate, lifetime), on_error)
