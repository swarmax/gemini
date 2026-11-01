"""The one rule for a value with a dimension: a public boundary takes a quantity, never a number."""

import numpy as np

from gemini import units
from gemini._utils.strings import join_names
from gemini.errors import ValidationError


def is_bare(value):
    """Return whether ``value`` is a number, an array or a list of numbers without a unit."""
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float, list, tuple, np.ndarray, np.generic))


def refuse(path, value, unit, quantity=None):
    """Raise ``invalid_value`` for a bare number given where the SI ``unit`` is the dimension.

    A value with a dimension is a ``Quantity`` or its ``{"value", "unit"}`` dict: a number alone
    does not say its unit. Nothing is raised for a value that is no bare number, or for a
    dimensionless ``unit`` (``None`` or ``"-"``), which stays a plain number.
    """
    if unit in (None, "-") or not is_bare(value):
        return
    accepted = ""
    if quantity is not None:
        accepted = f"; accepted units: {join_names(units.names(quantity))}"
    named = f"{quantity.replace('_', ' ')} in {unit!r}" if quantity else f"unit {unit!r}"
    raise ValidationError(
        f"{path} = {value!r}; expected {units.QUANTITY_FORM}, because it is a {named}{accepted}",
        path=path,
        code="invalid_value",
    )
