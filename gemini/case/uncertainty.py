"""The uncertainty of one number of the case: a distribution around its value, in SI."""

from typing import Literal

from gemini.case._utils.section import Section

KINDS = ("uniform", "triangular", "normal")
"""The distributions a value may declare."""


class Uncertainty(Section):
    """How a number of ``environment`` or ``assumptions`` may vary, in the SI unit of the value.

    ``uniform`` and ``triangular`` need ``min`` and ``max`` (the mode of a triangle is the value of
    the case). ``normal`` needs ``std`` (its mean is the value of the case) and may be truncated by
    ``min`` and ``max``. The value of the case lies inside ``[min, max]``.

    Attributes
    ----------
    kind : str
        One of ``uniform``, ``triangular`` and ``normal``.
    min, max : float or None
        The bounds.
    std : float or None
        The standard deviation of a ``normal``.
    """

    where = "uncertainty"
    kind: Literal["uniform", "triangular", "normal"]
    min: float | None = None
    max: float | None = None
    std: float | None = None

    def limits(self, value):
        """Return ``(low, high)``, the two ends a one-at-a-time sensitivity tries around ``value``.

        The bounds when there are, else ``value - std`` and ``value + std`` of a ``normal``.
        """
        low = self.min if self.min is not None else value - self.std
        high = self.max if self.max is not None else value + self.std
        return low, high
