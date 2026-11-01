"""The values of a case reach the modules of a plant by class, on a copy of the plant.

``apply_case`` sets, for a run, what the plant dict does not hold: the ground on every
``Formation``, the reservoir and the fluid on every reservoir and ``Doublet`` (at the depth of the
doublet), the air on every ``Atmosphere``, the return temperatures and the required supply
temperatures on the heating and cooling consumers. One private function does each kind. A value
the plant needs and the case lacks raises ``missing_value`` naming its path in the case.
"""

from copy import deepcopy

import numpy as np

from gemini._utils.strings import join_path
from gemini.case._utils.access import require
from gemini.modules.environment import Atmosphere, Formation
from gemini.modules.grids import CoolingGrid, HeatingGrid
from gemini.modules.subsurface import InjectionReservoir, ProductionReservoir
from gemini.plants.doublet import Doublet
from gemini.types import Fluid

RESERVOIRS = (ProductionReservoir, InjectionReservoir)
"""The classes that are a reservoir."""


def apply_case(plant, case):
    """Return a copy of ``plant`` with the values of ``case`` set by class.

    The plant of the user never changes. A plant without a module of a class needs none of its
    values, so a case may leave them out.
    """
    applied = deepcopy(plant)
    doublets = [path for path, module in applied.named_modules() if isinstance(module, Doublet)]
    _formations(applied, case, doublets)
    _reservoirs(applied, case, doublets)
    _doublets(applied, case, doublets)
    _air(applied, case)
    _consumers(applied, case)
    return applied


def _outside(path, doublets):
    """Return whether the module at ``path`` is no part of a doublet."""
    return not any(path.startswith(f"{doublet}.") for doublet in doublets)


def _fluid(case):
    """Return the ``Fluid`` of the reservoir brine from ``environment.fluid``."""
    fluid = case.environment.fluid if case.environment else None
    density = require(fluid, "density", "environment.fluid")
    viscosity = require(fluid, "viscosity", "environment.fluid")
    given = {"gas_liquid_ratio": fluid.gas_liquid_ratio, "gas_composition": fluid.gas}
    return Fluid(
        kind="brine",
        density=density,
        viscosity=viscosity,
        **{name: value for name, value in given.items() if value is not None},
    )


def _formations(plant, case, doublets):
    """Set the surface temperature and the gradient on every ``Formation`` outside a doublet."""
    for path, module in plant.named_modules():
        if isinstance(module, Formation) and _outside(path, doublets):
            plant.set_params(
                path,
                {
                    "geothermal_gradient": require(case, "environment.ground.gradient"),
                    "surface_temperature": require(case, "environment.ground.surface_temperature"),
                },
            )


def _reservoirs(plant, case, doublets):
    """Set the permeability, thickness, pressure and fluid on every reservoir outside a doublet."""
    for path, module in plant.named_modules():
        if isinstance(module, RESERVOIRS) and _outside(path, doublets):
            reference = require(case, "environment.reservoir.reference_depth")
            module.fluid = _fluid(case)
            plant.set_params(
                path,
                {
                    "permeability": require(case, "environment.reservoir.permeability"),
                    "aquifer_thickness": require(case, "environment.reservoir.thickness"),
                    "pressure": case.environment.pressure_at(reference),
                },
            )


def _doublets(plant, case, doublets):
    """Set the ground, the reservoir and the fluid on every ``Doublet``, at its own depth."""
    for path in doublets:
        doublet = plant.get_submodule(path)
        doublet.fluid = _fluid(case)
        values = {
            "gradient": require(case, "environment.ground.gradient"),
            "surface_temperature": require(case, "environment.ground.surface_temperature"),
            "thickness": require(case, "environment.reservoir.thickness"),
            "permeability": require(case, "environment.reservoir.permeability"),
        }
        if doublet.depth is not None:
            temperature = case.environment.temperature_at(doublet.depth)
            pressure = case.environment.pressure_at(doublet.depth)
            for limb in ("reservoir", "sink"):
                values[f"{limb}.temperature"] = temperature
                values[f"{limb}.pressure"] = pressure
        plant.set_params(path, values)


def _air(plant, case):
    """Set the air temperature on every ``Atmosphere``; a profile reaches it through the plan."""
    paths = [path for path, module in plant.named_modules() if isinstance(module, Atmosphere)]
    if not paths:
        return
    air = require(case, "environment.air.temperature")
    if isinstance(air, np.ndarray):
        return
    plant.set_inputs({join_path(path, "temperature"): air for path in paths})


def _consumers(plant, case):
    """Set the return temperature and the supply requirement on the heating and cooling consumers.

    The requirement is a minimum supply temperature for heat and a maximum for cold.
    """
    for grid, service, supply in (
        (HeatingGrid, "heating", "minimum_supply_temperature"),
        (CoolingGrid, "cooling", "maximum_supply_temperature"),
    ):
        demand = getattr(case.demand, service, None)
        for path, module in plant.named_modules():
            if not isinstance(module, grid) or demand is None:
                continue
            values = {
                "return_temperature": demand.return_temperature,
                supply: demand.supply_temperature,
            }
            plant.set_params(path, {name: v for name, v in values.items() if v is not None})
