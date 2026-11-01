"""Plants whose consumers are equipment with a cost, and runs of them, for the economics tests.

The consumers join the plant with ``add_module``, so the test classes stay out of the registry.
"""

import gemini as gm
from gemini.modules import CoolingGrid, ElectricityGrid, GasGrid, HeatingGrid
from gemini.modules._utils.cost import Equipment
from tests.fixtures.result_tables import make_results

HOURS = 24
"""Ticks of an hour in the runs below."""


class CostedHeatingGrid(Equipment, HeatingGrid):
    """A heat consumer that is equipment of the kind ``degasser``: a fixed item."""

    equipment_kind = "degasser"

    def capex(self, finance):
        """Return the capex factor of the kind."""
        return self.capex_of(finance)


class CostedCoolingGrid(Equipment, CoolingGrid):
    """A cooling consumer that is equipment of the kind ``flare``: a fixed item."""

    equipment_kind = "flare"

    def capex(self, finance):
        """Return the capex factor of the kind."""
        return self.capex_of(finance)


def _with_grids(plant):
    """Add the electricity and gas grids the bills of a run read."""
    plant._add_module("grid", ElectricityGrid())
    plant._add_module("gas", GasGrid())
    return plant


def heating_plant(costed=True):
    """Return a plant with one heat consumer, costed or not."""
    plant = gm.Plant("Heating")
    plant._add_module("heat", CostedHeatingGrid() if costed else HeatingGrid())
    return _with_grids(plant)


def cooling_plant():
    """Return a plant with one costed cooling consumer."""
    plant = gm.Plant("Cooling")
    plant._add_module("cool", CostedCoolingGrid())
    return _with_grids(plant)


def heating_cooling_plant():
    """Return a plant with a costed heat consumer and a costed cooling consumer."""
    plant = gm.Plant("HeatingCooling")
    plant._add_module("heat", CostedHeatingGrid())
    plant._add_module("cool", CostedCoolingGrid())
    return _with_grids(plant)


def day(heat=1000.0, cold=None, electricity=100.0, generated=None, fuel=None):
    """Return a day of hourly constant powers [W] at the edge modules."""
    sold = generated or 0.0
    columns = {
        "grid": {
            "power_out": [electricity] * HOURS,
            "power_in": [sold] * HOURS,
            "net_import": [max(electricity - sold, 0.0)] * HOURS,
            "net_export": [max(sold - electricity, 0.0)] * HOURS,
        }
    }
    if heat is not None:
        columns["heat"] = {
            "supply_in.enthalpy_flow": [heat] * HOURS,
            "return_out.enthalpy_flow": [0.0] * HOURS,
            "unmet_demand": [0.0] * HOURS,
            "operating": [1.0] * HOURS,
        }
    if cold is not None:
        columns["cool"] = {
            "supply_in.enthalpy_flow": [0.0] * HOURS,
            "return_out.enthalpy_flow": [cold] * HOURS,
        }
    if fuel is not None:
        columns["gas"] = {"gas_out.chemical_flow": [fuel] * HOURS}
    return make_results(columns)
