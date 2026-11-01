"""What each plant class contains and what a study may do with it, found from the code."""

from gemini._utils import registry
from gemini.modules.grids import CoolingGrid, HeatingGrid
from gemini.plants._utils.roles import roles_of
from gemini.plants.doublet import Doublet


def _count(plant, cls):
    """Return how many modules of class ``cls`` the plant has below its root."""
    return sum(isinstance(module, cls) for path, module in plant.named_modules() if path)


def _schedulable(plant):
    """Whether ``gm.schedule`` plans the plant: it has a doublet below its root.

    The schedule gives the flow of each ``Doublet`` that is a child of the plant, and raises
    ``invalid_design`` for more than one ``HeatingGrid`` or ``CoolingGrid``. A plant that is a
    doublet itself, or has none, gets no flow.
    """
    heating, cooling = _count(plant, HeatingGrid), _count(plant, CoolingGrid)
    return bool(_count(plant, Doublet)) and max(heating, cooling) <= 1


def _choices(plant):
    """Return the choices of a study the plant supports: ``doublets`` and ``depth``."""
    found = []
    if "doublets" in (getattr(plant, "_size", None) or {}):
        found.append("doublets")
    if "depth" in dict(plant.named_parameters(recurse=False)):
        found.append("depth")
    return found


def capabilities():
    """Return what each plant class contains, plans and lets a study choose.

    Every registered plant class is built at its smallest size and read. For each, the dict holds:

    - ``roles``: the roles (``gm.case.roles()``) of which it has a unit;
    - ``schedulable``: whether ``gm.schedule`` can plan it;
    - ``choices``: the choices of ``gm.case.Choices`` it supports, ``doublets`` when its class
      takes a structural size of that name and ``depth`` when it has a ``depth`` parameter.

    Returns
    -------
    dict
        ``{plant class name: {"roles": list, "schedulable": bool, "choices": list}}``.
    """
    result = {}
    for name in registry.names("plants"):
        plant = registry.get(name)()
        roles = {
            role for path, module in plant.named_modules() for role in roles_of(plant, path, module)
        }
        result[name] = {
            "roles": sorted(roles),
            "schedulable": _schedulable(plant),
            "choices": _choices(plant),
        }
    return result
