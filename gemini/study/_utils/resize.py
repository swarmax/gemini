"""A plant on another number of doublets: its plant dict with the doublets renumbered."""

import re
from copy import deepcopy

from gemini.errors import ValidationError

PATH_SECTIONS = ("params", "fluids", "inputs", "bindings", "param_history")
"""The sections of a plant dict whose keys start with a module path."""
_DOUBLET = re.compile(r"d(\d+)(?=\.|$)")


def _index(key):
    """Return the number of the doublet a key starts with, or ``None``."""
    found = _DOUBLET.match(key)
    return None if found is None else int(found.group(1))


def _renumbered(section, old, new):
    """Return ``section`` without the doublets from ``new`` on, and with the new ones as ``d0``."""
    kept = {key: value for key, value in section.items() if (_index(key) or 0) < new}
    for key, value in section.items():
        if _index(key) == 0:
            for number in range(old, new):
                copy = _DOUBLET.sub(f"d{number}", key, count=1)
                kept.setdefault(copy, deepcopy(value))
    return kept


def resized(plant, doublets):
    """Return a new plant of the same class and values on ``doublets`` doublets.

    The values stated on ``d0`` repeat on each added doublet; those of a removed doublet go. A
    plant whose class takes no structural size ``doublets`` raises ``invalid_design``, and a
    number its class does not allow raises the same from the class.
    """
    data = plant.to_dict()
    old = (data.get("size") or {}).get("doublets")
    if old is None:
        raise ValidationError(
            f"study: {type(plant).__name__} has no structural size 'doublets'; expected a plant "
            "class that takes it (see gm.plants.capabilities())",
            path="size.doublets",
            code="invalid_design",
        )
    data["size"] = {**data["size"], "doublets": doublets}
    for name in PATH_SECTIONS:
        data[name] = _renumbered(data.get(name, {}), old, doublets)
    return type(plant).from_dict(data)
