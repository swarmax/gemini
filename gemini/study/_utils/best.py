"""The best trial of a search: the objective as a value, with the plant that gave it."""

from dataclasses import dataclass
from typing import Any

from gemini.plants.plant import Plant
from gemini.types.shapes import Value
from gemini.units import Quantity


@dataclass(frozen=True, eq=False)
class Best(Value):
    """The objective of the best trial, a ``Value``, and the ``plant`` that gave it.

    ``best["plant"]`` is the plant too. ``to_dict`` is plain JSON: the plant as its plant dict
    (``None`` with no plant), the parameters of the trial as ``{value, unit}``; ``from_dict`` reads
    it back.
    """

    plant: Any = None

    def __getitem__(self, key):
        """Return the plant for ``"plant"``, else the part of the value of that name."""
        return self.plant if key == "plant" else self.parts[key]

    def to(self, unit, quantity=None):
        """Return the value in ``unit``, with the same plant."""
        converted = super().to(unit, quantity)
        return Best(converted.value, converted.unit, converted.reason, converted.parts, self.plant)

    def to_dict(self):
        """Return the JSON value of the objective with the ``plant`` as its plant dict."""
        plant = None if self.plant is None else self.plant.to_dict()
        return super().to_dict() | {"plant": plant}

    @classmethod
    def from_dict(cls, data):
        """Return the ``Best`` of ``to_dict``: parameters as quantities, the plant rebuilt."""
        parts = {
            key: item
            for key, item in data.items()
            if key not in ("value", "unit", "reason", "plant")
        }
        parameters = parts.get("parameters")
        if parameters is not None:
            parts["parameters"] = {
                name: Quantity.from_dict(item) for name, item in parameters.items()
            }
        plant = None if data["plant"] is None else Plant.from_dict(data["plant"])
        return cls(data["value"], data["unit"], data.get("reason"), parts, plant)

    __hash__ = Value.__hash__
