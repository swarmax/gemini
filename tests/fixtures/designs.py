"""Design values for tests: what a module needs that its declaration no longer defaults.

A module declares no design value, so a test that runs a module sets them. ``with_values`` sets the
values of the tests in one place, for a module or a whole plant, and leaves any value the test
or the plant already holds.
"""

from gemini.physics import combustion, gas
from tests.fixtures import si
from tests.fixtures.esp_design import ESP_DESIGN

WELL = {
    "friction_correlation": "darcy_weisbach",
    "two_phase_friction_correlation": "BeggsBrill",
    "correction_factors": (1.0, 0.0),
    "heat_transfer_coefficient": 10.0,
}
RESERVOIR = {"skin": 0.0, "decline_threshold": 0.15}
VALUES = {
    "AbsorptionUnit": {"thermal_cop": 0.7, "minimum_driving_temperature": 353.15},
    "AdsorptionChiller": {
        "thermal_cop": 0.55,
        "minimum_driving_temperature": 328.15,
        "maximum_driving_temperature": 363.15,
    },
    "HeatExchanger": {"arrangement": "counterflow", "fouling_threshold": 0.15},
    "GasGrid": {"composition": dict(gas.GRID_COMPOSITION)},
    "HeatPump": {
        "cop_model": "carnot",
        "carnot_fraction": 0.5,
        "lorenz_fraction": 0.5,
        "minimum_temperature_lift": 10.0,
    },
    "Pipe": {"roughness": 4.5e-5},
    "Valve": {"characteristic": "equal_percentage", "rangeability": 50.0},
    "FlashTurbine": {"isentropic_efficiency": 0.85, "baumann_factor": 1.0},
    "CirculationPump": {"efficiency": 0.55},
    "GasCompressor": {"stage_count": 1},
    "AquiferStorage": {"storage_period": 182.625 * 86400.0},
    "IceStorage": {"initial_ice_fraction": 0.0, "initial_temperature": 273.15},
    "ThermalStorage": {
        "charge_effectiveness": 1.0,
        "discharge_effectiveness": 1.0,
        "initial_temperature": 293.15,
    },
    "ProductionReservoir": RESERVOIR,
    "InjectionReservoir": RESERVOIR,
    "Degasser": {"nominal_pressure_drop": 14900.0, "separation_efficiency": 0.0},
    "Filter": {
        "nominal_pressure_drop": 1600.0,
        "nominal_mass_flow": 149 / 3600 * 1068,
        "clogging_pressure_drop": 50000.0,
    },
    "Flare": {"combustion_efficiency": float(combustion.FLARE_EFFICIENCY)},
    "ProductionWell": WELL,
    "InjectionWell": WELL,
    "Doublet": {"drainage_radius": 1000.0, "roughness": 4.5e-5},
    "ESP": {name.removeprefix("esp."): value for name, value in ESP_DESIGN.items()},
}
"""The value each class took as its default before, by class name."""


def design_values(module):
    """Return the values of ``VALUES`` that ``module`` and its descendants lack, by dotted path."""
    values = {}
    for path, child in module.named_modules():
        known = {
            k: v
            for cls in reversed(type(child).__mro__)
            for k, v in VALUES.get(cls.__name__, {}).items()
        }
        for name, value in known.items():
            declaration = child._parameters[name] if name in child._parameters else None
            if declaration is None or declaration.initialized and declaration.value is not None:
                continue
            values[f"{path}.{name}" if path else name] = value
    return values


def with_values(module, **values):
    """Return ``module`` with the design values it lacks set, then ``values`` (SI, by path)."""
    module.set_params("", si.params(module, design_values(module) | values))
    return module
