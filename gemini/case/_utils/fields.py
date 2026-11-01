"""The field types of the case: a quantity stored in SI, and a map of quantities.

``Q("length")`` marks a field whose value arrives as a ``Quantity`` or its dict and is stored as a
plain SI number, or as an array for a profile. A plain number is accepted only for a dimensionless
quantity. ``QMap`` does the same for a dict of such values.
"""

import math
from dataclasses import dataclass

import numpy as np
from pydantic_core import core_schema

from gemini import units
from gemini._utils.strings import join_names
from gemini.errors import ValidationError


def si_unit_of(quantity):
    """Return the SI unit string of a named quantity, such as ``"m3/s"`` for ``volume_flow``."""
    return units.si_unit(units.names(quantity)[0])


def to_si(value, quantity, profile=False):
    """Return ``value`` in SI: a float, or an array when ``profile`` is true and it is one.

    ``value`` is a ``Quantity`` or its dict. A plain number passes only for a quantity without a
    dimension. Raises ``ValidationError``: ``invalid_value`` for text, a boolean, a number with a
    dimension or a value that is not finite, ``invalid_unit`` for a unit of another dimension.
    """
    if isinstance(value, dict):
        value = units.Quantity.from_dict(value)
    if isinstance(value, units.Quantity):
        return _quantity_si(value, quantity, profile)
    dimensionless = si_unit_of(quantity) == "-"
    if dimensionless and isinstance(value, (int, float)) and not isinstance(value, bool):
        return _finite(float(value))
    raise ValidationError(
        f"value = {value!r}; expected {units.QUANTITY_FORM}"
        + ("" if not dimensionless else ", or a number"),
        code="invalid_value",
    )


def _quantity_si(given, quantity, profile):
    """Return a ``Quantity`` in SI, its unit checked against the dimension of ``quantity``."""
    if not units.fits(given.unit, quantity):
        allowed = units.names(quantity)
        raise ValidationError(
            f"unit {str(given.unit)!r} is not a {quantity.replace('_', ' ')}; expected one of "
            f"{join_names(allowed)}",
            code="invalid_unit",
        )
    array = isinstance(given.value, np.ndarray)
    if array and not profile:
        raise ValidationError(
            "value is a list; expected one number, because this value has no profile",
            code="invalid_value",
        )
    if array:
        return _finite(np.asarray(units.array_to_si(given.value, given.unit, quantity)))
    return _finite(units.to_si(given.value, given.unit, quantity))


def _finite(value):
    """Return ``value`` unless a number of it is not finite."""
    if not np.all(np.isfinite(value)):
        raise ValidationError("value is not finite; expected a number", code="invalid_value")
    return value


def _bounded(value, quantity, minimum, maximum):
    """Return ``value`` unless it breaks ``minimum`` or ``maximum``, each ``(limit, strict)``."""
    if minimum is not None:
        limit, strict = minimum
        if np.any(value <= limit if strict else value < limit):
            raise _bound_error(value, quantity, f"{'more than' if strict else 'at least'} {limit}")
    if maximum is not None:
        limit, strict = maximum
        if np.any(value >= limit if strict else value > limit):
            raise _bound_error(value, quantity, f"{'less than' if strict else 'at most'} {limit}")
    return value


def _bound_error(value, quantity, expected):
    """Return the ``out_of_bounds`` error of a value, in the SI unit of its quantity."""
    return ValidationError(
        f"value is {float(np.ravel(value)[0])} {si_unit_of(quantity)}; expected {expected}",
        code="out_of_bounds",
    )


@dataclass(frozen=True)
class Q:
    """A field holding the quantity ``quantity`` in SI; ``profile`` also takes an array.

    ``minimum`` and ``maximum`` are ``(limit, strict)`` in SI.
    """

    quantity: str
    profile: bool = False
    minimum: tuple | None = None
    maximum: tuple | None = None

    def convert(self, value):
        """Return ``value`` in SI, or ``None`` when it is absent."""
        if value is None:
            return None
        found = to_si(value, self.quantity, self.profile)
        return _bounded(found, self.quantity, self.minimum, self.maximum)

    def __get_pydantic_core_schema__(self, source, handler):
        """Convert the value before pydantic checks its type."""
        return core_schema.no_info_before_validator_function(self.convert, handler(source))


@dataclass(frozen=True)
class QMap:
    """A field holding a dict of quantities of one kind, keyed from ``keys``."""

    quantity: str
    keys: tuple

    def convert(self, value):
        """Return the dict with every value in SI, or ``None`` when it is absent."""
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValidationError(
                f"value = {value!r}; expected a dict of {join_names(self.keys)} to a value",
                code="invalid_value",
            )
        unknown = [key for key in value if key not in self.keys]
        if unknown:
            raise ValidationError(
                f"key {unknown[0]!r} is unknown; expected one of {join_names(self.keys)}",
                code="unknown_name",
            )
        return {key: to_si(item, self.quantity) for key, item in value.items()}

    def __get_pydantic_core_schema__(self, source, handler):
        """Convert the dict before pydantic checks its type."""
        return core_schema.no_info_before_validator_function(self.convert, handler(source))


@dataclass(frozen=True)
class Shape:
    """The JSON Schema of a field whose type pydantic cannot describe, such as a date."""

    schema: dict


def quantity_dict(value, quantity):
    """Return the dict of an SI ``value`` of ``quantity``; a dimensionless scalar stays a number."""
    unit = si_unit_of(quantity)
    if unit == "-" and not isinstance(value, np.ndarray):
        return value
    shown = value.tolist() if isinstance(value, np.ndarray) else value
    return {"value": shown, "unit": unit}


def quantity_schema(quantity, profile=False):
    """Return the JSON Schema of a value of ``quantity``: ``{"value", "unit"}``."""
    number = {"type": "number"}
    value = {"anyOf": [number, {"type": "array", "items": number}]} if profile else number
    form = {
        "type": "object",
        "required": ["value", "unit"],
        "additionalProperties": False,
        "properties": {"value": value, "unit": {"enum": units.names(quantity)}},
    }
    if si_unit_of(quantity) == "-":
        return {"anyOf": [number, form]}
    return form


def is_number(value):
    """Whether ``value`` is a finite real number that is no boolean."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


__all__ = [
    "Q",
    "QMap",
    "Shape",
    "to_si",
    "si_unit_of",
    "quantity_dict",
    "quantity_schema",
    "is_number",
]
