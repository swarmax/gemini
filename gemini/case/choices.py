"""The choices of a case: what a study may vary, each as a range."""

from typing import Annotated, Any

from pydantic import Field, field_validator, model_validator

from gemini import units
from gemini.case._utils.fields import Shape, is_number, quantity_schema, to_si
from gemini.case._utils.section import Section
from gemini.errors import ValidationError

_END = Shape({"anyOf": [{"type": "number"}, quantity_schema("length")]})


class Range(Section):
    """A closed range ``min <= max`` of counts or of lengths.

    ``Range(1, 3)`` is a range of counts; ``Range(Quantity(2000, "m"), Quantity(3500, "m"))`` is a
    range of lengths, stored in SI.

    Attributes
    ----------
    min, max : float
        The ends; metres when the range is of lengths.
    unit : str or None
        ``"m"`` for a range of lengths, ``None`` for a range of counts.
    """

    where = "choices"
    min: Annotated[Any, _END]
    max: Annotated[Any, _END]
    unit: str | None = Field(default=None, json_schema_extra={"hidden": True})

    def __init__(self, min=None, max=None, **data):
        """Take the two ends as positional arguments or keywords."""
        super().__init__(min=min, max=max, **data)

    @model_validator(mode="before")
    @classmethod
    def _ends(cls, data):
        """Turn the ends to SI and record their unit."""
        if not isinstance(data, dict) or data.get("unit") is not None:
            return data
        low, high = _end(data.get("min"), "min"), _end(data.get("max"), "max")
        if low[1] != high[1]:
            raise ValidationError(
                "min and max differ in kind; expected two counts or two lengths",
                code="invalid_unit",
            )
        if low[0] > high[0]:
            raise ValidationError(
                f"min = {low[0]} is above max = {high[0]}; expected min <= max",
                code="out_of_bounds",
            )
        return {"min": low[0], "max": high[0], "unit": low[1]}

    def to_dict(self):
        """Return the range as plain data, the ends as lengths when it has a unit."""
        if self.unit is None:
            return {"min": self.min, "max": self.max}
        return {name: {"value": getattr(self, name), "unit": self.unit} for name in ("min", "max")}


def _end(value, name):
    """Return ``(number, "m" or None)`` of one end: a length in SI, or a plain number."""
    if isinstance(value, (dict, units.Quantity)):
        return to_si(value, "length"), "m"
    if not is_number(value):
        raise ValidationError(
            f"{name} = {value!r}; expected a number or {units.QUANTITY_FORM}", code="invalid_value"
        )
    return value, None


class Choices(Section):
    """What a study may vary: the number of doublets and their depth.

    Attributes
    ----------
    doublets : Range or None
        Whole numbers of doublets, at least 1.
    depth : Range or None
        Depths [m] of the doublets, 0 or more.
    """

    where = "choices"
    doublets: Range | None = None
    depth: Range | None = None

    @field_validator("doublets")
    @classmethod
    def _counts(cls, doublets):
        """Refuse a range that is not of whole numbers from 1."""
        if doublets is None:
            return doublets
        ends = (doublets.min, doublets.max)
        if doublets.unit is not None or any(end != int(end) or end < 1 for end in ends):
            raise ValidationError(
                f"range = {ends}; expected whole numbers of at least 1, without a unit",
                code="out_of_bounds",
            )
        return doublets

    @field_validator("depth")
    @classmethod
    def _lengths(cls, depth):
        """Refuse a range that is not of lengths of 0 or more."""
        if depth is None:
            return depth
        if depth.unit != "m" or depth.min < 0:
            raise ValidationError(
                "range is not of lengths from 0; expected Quantity ends such as "
                "{'value': 2000, 'unit': 'm'}",
                code="invalid_unit",
            )
        return depth
