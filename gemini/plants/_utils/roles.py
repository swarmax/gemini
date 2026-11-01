"""What a module is for in a plant, found from its class and its wiring, never from its name."""

from gemini._utils.strings import join_path
from gemini.modules.cooling import AbsorptionUnit, AdsorptionChiller
from gemini.modules.exchangers import HeatExchanger
from gemini.modules.grids import CoolingGrid, HeatingGrid
from gemini.modules.heating import CHP, Boiler, HeatPump
from gemini.plants.doublet import Doublet

CLASSES = {
    "doublet": Doublet,
    "boiler": Boiler,
    "chp": CHP,
    "heat_exchanger": HeatExchanger,
    "heating_supply": HeatingGrid,
    "cooling_supply": CoolingGrid,
}
"""The roles that the class of a module alone decides."""
ROLES = (*CLASSES, "heat_pump", "chiller")
"""Every role a module can have."""


def _reaches(plant, path, port, grid):
    """Return whether the outlet ``path.port`` feeds a module of class ``grid``."""
    fed = plant.feeds(join_path(path, port))
    return any(isinstance(plant.get_submodule(item), grid) for item in fed)


def roles_of(plant, path, module):
    """Return the roles of ``module`` at ``path`` in ``plant``.

    A heat pump is a ``heat_pump`` when its ``sink_out`` reaches a ``HeatingGrid`` and a
    ``chiller`` when its ``source_out`` reaches a ``CoolingGrid``; an absorption or adsorption
    unit is a ``chiller`` when its ``chilled_out`` reaches a ``CoolingGrid``.
    """
    found = [role for role, cls in CLASSES.items() if isinstance(module, cls)]
    if isinstance(module, HeatPump):
        if _reaches(plant, path, "sink_out", HeatingGrid):
            found.append("heat_pump")
        if _reaches(plant, path, "source_out", CoolingGrid):
            found.append("chiller")
    if isinstance(module, (AbsorptionUnit, AdsorptionChiller)):
        if _reaches(plant, path, "chilled_out", CoolingGrid):
            found.append("chiller")
    return found


def units_of(plant, role):
    """Return the paths of the modules of ``role`` in ``plant``; the root is the path ``""``."""
    return [path for path, module in plant.named_modules() if role in roles_of(plant, path, module)]
