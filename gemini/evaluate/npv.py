"""Net present value of a plant run."""

from gemini.evaluate._utils.cashflow import net_cash_flow
from gemini.evaluate._utils.cost import annuity
from gemini.evaluate._utils.discounting import discounting
from gemini.evaluate._utils.outcome import reported, unavailable
from gemini.run._utils.apply import apply_case
from gemini.types.shapes import measure


def npv(plant, case, results, discount_rate=None, lifetime=None, on_error="raise"):
    """Return the net present value [currency]: ``-capex + (revenue - opex) * A``.

    ``A`` is the annuity factor, the sum over the lifetime years of ``1 / (1 + rate) ** t``.
    The yearly revenue is the heat and cold delivered per year at the prices of ``heat`` and
    ``cold``, integrated over the run when a price follows the demand; the yearly cost is
    ``opex``. Both are constant over the lifetime, with no degradation, tax, replacement or
    residual value.

    Parameters
    ----------
    plant : Module
        The plant of the run.
    case : Case
        Its finance gives the prices, and the rate and lifetime when not given below. Anything
        needed and given nowhere raises ``ValidationError`` (code ``missing_assumption``).
    results : Results
        The finished run of the plant.
    discount_rate : float, optional
        Real discount rate per year [-]; ``assumptions.finance.discount_rate`` when ``None``.
    lifetime : float, optional
        Years of operation; ``assumptions.finance.lifetime`` when ``None``.
    on_error : {"raise", "record"}, optional
        A value the inputs cannot give raises; ``"record"`` makes it ``None`` with a ``reason``.

    Returns
    -------
    Value
        A ``gm.units.Quantity`` in SI, with the parts of the result in ``parts`` (``to_plain``
        gives the JSON). ``{value, unit, capex, net_cash_flow, discount_rate,
        lifetime_years}``, the last four each
        a value, with ``value`` and ``capex`` in the currency (``unit``) and ``net_cash_flow`` in
        currency per year. A plant without equipment with a cost has no value.
    """
    return reported(
        on_error,
        "currency",
        lambda: _npv(plant, case, results, (discount_rate, lifetime), on_error),
    )


def _npv(plant, case, results, discount, on_error):
    """Return the net present value; ``on_error`` applies to a plant without a cost."""
    rate, years = discounting(case, *discount)
    cost, flow, unit, reason = net_cash_flow(apply_case(plant, case), case, results, on_error)
    if cost is None:
        return unavailable(unit, reason, on_error)
    return measure(
        flow * annuity(rate, years) - cost,
        unit,
        capex=measure(cost, unit),
        net_cash_flow=measure(flow, "currency/yr"),
        discount_rate=measure(rate, "-"),
        lifetime_years=measure(years, "yr"),
    )
