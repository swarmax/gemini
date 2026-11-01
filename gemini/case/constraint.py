"""One limit of a case: a quantity of a role, with its bounds."""

from typing import Annotated, Any, Literal

from pydantic import ValidationInfo, field_validator, model_validator

from gemini.case._utils.fields import Shape, quantity_dict, to_si
from gemini.case._utils.section import Section
from gemini.case.roletable import check_role, reads
from gemini.errors import ValidationError

_BOUND = Shape({"anyOf": [{"type": "number"}, {"type": "object"}]})


class Constraint(Section):
    """A limit on a quantity of a role; it applies to every unit of the role on its own.

    ``on`` and ``quantity`` come from ``gm.case.roles()``. ``over`` is ``each`` (every step),
    ``sum``, ``mean``, ``max`` or ``min`` (one figure of the run) or ``duration`` (the total time
    of the steps where ``when`` holds, with bounds that are durations). ``when`` is ``always`` or
    ``running``, the steps where the unit carries flow. A bound is a ``Quantity`` or its dict,
    stored in SI; a plain number only for a quantity without a dimension. At least one of ``min``,
    ``max`` and ``equals``.

    Attributes
    ----------
    on, quantity : str
        The role and its quantity.
    over, when : str
        How the run is read, and which steps count.
    min, max, equals : float or None
        The bounds, SI.
    """

    where = "constraint"
    on: str
    quantity: str
    over: Literal["each", "sum", "mean", "max", "min", "duration"] = "each"
    when: Literal["always", "running"] = "always"
    min: Annotated[Any, _BOUND] = None
    max: Annotated[Any, _BOUND] = None
    equals: Annotated[Any, _BOUND] = None

    @field_validator("on")
    @classmethod
    def _role(cls, role):
        """Return the role, or raise ``unknown_name``."""
        return check_role(role)

    @field_validator("quantity")
    @classmethod
    def _quantity(cls, quantity, info: ValidationInfo):
        """Return the quantity, or raise unless the role has it."""
        if "on" in info.data:
            reads(info.data["on"], quantity)
        return quantity

    @field_validator("min", "max", "equals", mode="before")
    @classmethod
    def _bound(cls, bound, info: ValidationInfo):
        """Return a bound in SI, in the dimension of the quantity (a duration over time)."""
        if bound is None or not {"on", "quantity", "over"} <= set(info.data):
            return bound
        dimension = reads(info.data["on"], info.data["quantity"]).dimension
        return to_si(bound, "duration" if info.data["over"] == "duration" else dimension)

    @model_validator(mode="after")
    def _ordered(self):
        """Refuse a limit without a bound, an ``equals`` with another bound, or min above max."""
        bounds = [self.min, self.max, self.equals]
        if all(bound is None for bound in bounds):
            raise ValidationError("expected min, max or equals", code="missing_value")
        if self.equals is not None and (self.min is not None or self.max is not None):
            raise ValidationError(
                "equals is given with min or max; expected one or the other",
                code="conflicting_value",
            )
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValidationError(
                f"min = {self.min} is above max = {self.max}; expected min <= max",
                code="out_of_bounds",
            )
        return self

    @property
    def dimension(self):
        """The quantity of the bounds: the role's quantity, or a duration over ``duration``."""
        return "duration" if self.over == "duration" else reads(self.on, self.quantity).dimension

    def to_dict(self):
        """Return the constraint as plain data, the bounds in SI."""
        data = super().to_dict()
        for name in ("min", "max", "equals"):
            if data.get(name) is not None:
                data[name] = quantity_dict(data[name], self.dimension)
        return data
