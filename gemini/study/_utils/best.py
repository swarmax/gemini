"""The best trial of a search: the objective as a value, with the plant that gave it."""

from dataclasses import dataclass
from typing import Any

from gemini.types.shapes import Value


@dataclass(frozen=True, eq=False)
class Best(Value):
    """The objective of the best trial, a ``Value``, and the ``plant`` that gave it.

    ``best["plant"]`` is the plant too. The plant is no part of the JSON form, ``to_dict``.
    """

    plant: Any = None

    def __getitem__(self, key):
        """Return the plant for ``"plant"``, else the part of the value of that name."""
        return self.plant if key == "plant" else self.parts[key]

    def to(self, unit, quantity=None):
        """Return the value in ``unit``, with the same plant."""
        converted = super().to(unit, quantity)
        return Best(converted.value, converted.unit, converted.reason, converted.parts, self.plant)

    __hash__ = Value.__hash__
