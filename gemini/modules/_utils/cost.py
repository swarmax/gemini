"""What a module costs: its capex and fixed opex from the finance section of a case."""

from gemini.errors import ValidationError
from gemini.physics import costs

FINANCE = "assumptions.finance"
"""The path of the finance section in a case."""


def _missing(path):
    """Return the error of a cost value that the case does not give."""
    return ValidationError(
        f"{path} is missing; expected a value in the case (it has no default)",
        path=path,
        code="missing_assumption",
    )


def capex_factor(finance, kind):
    """Return the capex factor of ``kind`` in SI, or raise ``missing_assumption`` naming it."""
    factor = getattr(finance.capex, kind, None)
    if factor is None:
        raise _missing(f"{FINANCE}.capex.{kind}")
    return factor


def fixed_share(finance, kind):
    """Return the yearly fixed opex of ``kind`` as a share of its capex [1/yr], or raise."""
    share = (finance.opex.fixed if finance.opex is not None else None) or {}
    if share.get(kind) is None:
        raise _missing(f"{FINANCE}.opex.fixed.{kind}")
    return share[kind]


class Equipment:
    """A module that is equipment: it has a kind, a capex and a fixed opex.

    A subclass sets ``equipment_kind`` to one of ``gemini.case._utils.kinds.EQUIPMENT_KINDS`` and
    defines ``capex(finance)``, the capex factor of its kind times its size, in the currency of
    the case. ``finance`` is ``case.assumptions.finance``. A factor or a share that the case lacks
    raises ``ValidationError`` (code ``missing_assumption``) naming its path.
    """

    equipment_kind = None

    def capex_of(self, finance, size=1.0):
        """Return the capex factor of the kind of this module times ``size``."""
        return costs.scaled(capex_factor(finance, self.equipment_kind), size)

    def fixed_opex(self, finance):
        """Return the fixed opex of a year [currency/yr]: the share of the kind times the capex."""
        return costs.scaled(fixed_share(finance, self.equipment_kind), self.capex(finance))
