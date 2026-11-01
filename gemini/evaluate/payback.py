"""Simple payback time of a plant run."""

from gemini.evaluate._utils.cashflow import net_cash_flow
from gemini.evaluate._utils.outcome import reported, unavailable
from gemini.types.shapes import measure


def payback(plant, problem, results, on_error="raise"):
    """Return the simple payback time [year]: ``capex / (revenue - opex)``, without discounting.

    Parameters
    ----------
    plant : Module
        The plant of the run.
    problem : Problem
        Its assumptions give the prices of ``heat``, ``cold`` and energy, as for ``npv``; anything
        needed and missing raises ``ValidationError`` (code ``missing_assumption``).
    results : Results
        The finished run of the plant.
    on_error : {"raise", "record"}, optional
        A value the inputs cannot give raises; ``"record"`` makes it ``None`` with a ``reason``.

    Returns
    -------
    Value
        A ``gm.units.Quantity`` in SI, with the parts of the result in ``parts`` (``to_plain``
        gives the JSON). ``{value, unit, capex, net_cash_flow}`` with ``unit`` ``"yr"`` and
        the last two each a
        value. A plant that declares no cost, or whose yearly revenue does not exceed its yearly
        cost (it never pays back), has no value.
    """
    return reported(on_error, "yr", lambda: _payback(plant, problem, results, on_error))


def _payback(plant, problem, results, on_error):
    """Return the payback time; ``on_error`` applies to a value the plant cannot give."""
    cost, flow, unit, reason = net_cash_flow(problem.apply_site(plant), problem, results, on_error)
    if cost is None:
        return unavailable("yr", reason, on_error)
    details = dict(capex=measure(cost, unit), net_cash_flow=measure(flow, "currency/yr"))
    if flow <= 0:
        reason = "the yearly revenue does not exceed the yearly cost"
        return unavailable("yr", reason, on_error, **details)
    return measure(cost / flow, "yr", **details)
