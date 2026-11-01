"""Variables named after a role of the plant: ``<role>.<parameter>`` reaches every unit of it."""

from gemini import units
from gemini._utils.strings import join_path
from gemini.errors import GeminiError
from gemini.plants._utils.roles import ROLES, units_of
from gemini.study._utils.target import unit_of

DEPTH = "depth"
"""The depth: the plant's own, or else the depth of every doublet."""


def _has(plant, name):
    """Whether ``name`` is a name of ``plant``."""
    try:
        plant.get(name)
    except GeminiError:
        return False
    return True


def concrete(plant, name):
    """Return the names of ``plant`` that the variable ``name`` stands for.

    ``<role>.<parameter>`` (a role of ``gm.case.roles()``) is that parameter of each unit of the
    role (``plant.<parameter>`` that of the plant itself), and none when the plant has no unit of
    it; a role wins over a path of the same text.
    ``depth`` on a plant with no depth of its own is the depth of each doublet. Any other name,
    such as a path or ``case.<path>``, stands for itself.
    """
    role, _, parameter = name.partition(".")
    if role in ROLES and parameter and "." not in parameter:
        return [join_path(path, parameter) for path in units_of(plant, role)]
    if name == DEPTH and not _has(plant, name) and units_of(plant, "doublet"):
        return [join_path(path, DEPTH) for path in units_of(plant, "doublet")]
    return [name]


def expanded(plant, values):
    """Return the SI ``values`` by name as ``{concrete name: number}`` for ``plant``."""
    return {path: number for name, number in values.items() for path in concrete(plant, name)}


def quantities(plant, case, values):
    """Return ``{name: Quantity}`` for SI values, each in the SI unit of its first concrete name."""
    return {
        name: units.Quantity(number, unit_of(plant, case, concrete(plant, name)[0]))
        for name, number in values.items()
    }
