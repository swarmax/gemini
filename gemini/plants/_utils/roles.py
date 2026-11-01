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
PLANT = "plant"
"""The role of the plant itself, at the root path ``""``."""
ROLES = (*CLASSES, "heat_pump", "chiller", PLANT)
"""Every role a module can have."""
DELIVERY = {
    "heat_pump": {HeatPump: ("sink_out", "sink_in")},
    "boiler": {Boiler: ("fluid_out", "fluid_in")},
    "chp": {CHP: ("fluid_out", "fluid_in")},
    "chiller": {
        HeatPump: ("source_in", "source_out"),
        AbsorptionUnit: ("chilled_in", "chilled_out"),
        AdsorptionChiller: ("chilled_in", "chilled_out"),
    },
}
"""For each role and class, the two ports whose enthalpy flows, first less second, give the power
the unit delivers: heat to its water, or cold from its chilled water."""


def _reaches(plant, path, port, grid):
    """Return whether the outlet ``path.port`` feeds a module of class ``grid``."""
    fed = plant.feeds(join_path(path, port))
    return any(isinstance(plant.get_submodule(item), grid) for item in fed)


def roles_of(plant, path, module):
    """Return the roles of ``module`` at ``path`` in ``plant``.

    A heat pump is a ``heat_pump`` when its ``sink_out`` reaches a ``HeatingGrid`` and a
    ``chiller`` when its ``source_out`` reaches a ``CoolingGrid``; an absorption or adsorption
    unit is a ``chiller`` when its ``chilled_out`` reaches a ``CoolingGrid``. The root is also
    the ``plant``.
    """
    found = [role for role, cls in CLASSES.items() if isinstance(module, cls)]
    if not path:
        found.append(PLANT)
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


def delivery_ports(module, role):
    """Return ``(first, second)``, the ports whose enthalpy flows give the power ``module`` gives.

    The power is the flow of ``first`` less that of ``second``. ``None`` for a class of the role
    with no such pair.
    """
    for cls, ports in DELIVERY[role].items():
        if isinstance(module, cls):
            return ports
    return None
