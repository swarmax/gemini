"""The discount rate and the lifetime of a case."""

from gemini import units
from gemini.case._utils.access import require
from gemini.errors import ValidationError


def discounting(case, discount_rate, lifetime):
    """Return ``(rate, years)``: the explicit arguments, else those of ``case``.

    A value given nowhere raises ``ValidationError`` (code ``missing_assumption``); a negative rate
    or a lifetime under one year raises ``ValidationError``.
    """
    rate = discount_rate
    if rate is None:
        rate = require(case, "assumptions.finance.discount_rate")
    years = lifetime
    if years is None:
        years = require(case, "assumptions.finance.lifetime") / units.Quantity(1, "yr").si
    if rate < 0:
        raise ValidationError(
            f"discount_rate = {rate}; expected a rate of 0 or more", path="discount_rate"
        )
    if years < 1:
        raise ValidationError(f"lifetime = {years}; expected 1 year or more", path="lifetime")
    return rate, years
