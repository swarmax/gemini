"""Evaluate the immutable phase-0 golden cases through the current public APIs.

``golden_values.json`` holds one case per captured result. ``evaluate_case`` turns a case's
inputs and parameters into outputs with the original names and units, one function per case
family. ``assert_values`` is the shared comparison for every captured-number test.
"""

import json

import pytest

from gemini import units
from gemini.analysis import estimate_reservoir_pressure
from gemini.modules.pumps import ESP
from gemini.modules.subsurface import InjectionReservoir, ProductionReservoir
from gemini.modules.wells import InjectionWell, ProductionWell
from gemini.physics import chemistry, corrosion, erosion, geometry, heat_transfer, hydraulics
from gemini.types.flows import Stream
from gemini.types.fluid import Fluid
from gemini.units import Quantity
from tests.fixtures import FIXTURES, si
from tests.fixtures.designs import WELL
from tests.fixtures.esp_design import ESP_MODULE
from tests.fixtures.old_names import RENAMED_NAMES

GOLDEN_VALUES = FIXTURES / "golden_values.json"
HYDRAULIC_CORRELATIONS = {
    "darcy": hydraulics.darcy_weisbach_dp,
    "beggs": hydraulics.beggs_brill_dp,
}


def golden_cases():
    """Return the immutable phase-0 cases keyed by case name."""
    return json.loads(GOLDEN_VALUES.read_text())


def assert_values(actual, expected):
    """Recursively compare numeric leaves within 1e-9 relative, keeping strings and nulls exact."""
    if isinstance(expected, dict):
        current = {RENAMED_NAMES.get(key, key): value for key, value in expected.items()}
        assert actual.keys() == current.keys()
        for key in current:
            assert_values(actual[key], current[key])
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for left, right in zip(actual, expected):
            assert_values(left, right)
    elif isinstance(expected, (int, float)):
        assert actual == pytest.approx(expected, rel=1e-9, abs=0)
    else:
        assert actual == expected


def configured(module_class, parameters):
    """Build a standalone module and set its parameters as explicit values."""
    module = module_class()
    si.set_params(
        module, "", {RENAMED_NAMES.get(key, key): value for key, value in parameters.items()}
    )
    return module


def evaluate():
    """Return all phase-0 outputs in their original names and units for comparison."""
    return {name: {"expected": evaluate_case(name, case)} for name, case in golden_cases().items()}


def evaluate_case(name, case):
    """Return one golden case's outputs, dispatched on the case name."""
    parameters, inputs = case.get("parameters", {}), case["inputs"]
    if name.startswith("esp_"):
        return _esp(parameters, inputs)
    if name in RESERVOIR_CASES:
        return RESERVOIR_CASES[name](inputs)
    if name.startswith("well_"):
        return _well(name == "well_production", parameters, inputs)
    if name in HYDRAULIC_CORRELATIONS:
        return HYDRAULIC_CORRELATIONS[name](*inputs)
    if name == "temperature":
        return _temperature_change(inputs)
    if name.startswith("corrosion_"):
        return _corrosion(name.endswith("True"), parameters, inputs)
    if name == "chemistry":
        return _co2_partial_pressure(inputs)
    if name.startswith("erosion_"):
        return _erosion(parameters["erosion_model"], inputs)
    raise AssertionError(f"Uncovered golden case {name}")


def _esp(parameters, inputs):
    """Evaluate the ESP polynomial at one frequency; efficiency in percent as captured."""
    outputs = configured(ESP, ESP_MODULE | parameters)(
        frequency=inputs["pump_freq"],
        fluid_in=Stream(
            m_dot=Quantity(inputs["pump_flow"] * 1000, "kg/s"),
            T=Quantity(300, "K"),
            p=Quantity(1e5, "Pa"),
        ),
    ).outputs
    return dict(pump_head=outputs.head, pump_power=outputs.power, pump_eff=outputs.efficiency * 100)


def _reservoir_parameters():
    """Return the shared phase-0 reservoir design in SI units."""
    return dict(
        pressure=22e6,
        temperature=353.15,
        permeability=units.md_to_m2(10000),
        aquifer_thickness=45,
        drainage_radius=1000,
        top_depth=1800,
        wellbore_radius=0.0765,
        skin=0.0,
        productivity_index=units.index_to_si(21),
        injectivity_index=units.index_to_si(20),
    )


def _injection_ipr(inputs):
    """Evaluate the injection inflow performance at one sandface flow."""
    reservoir = configured(InjectionReservoir, _reservoir_parameters())
    outputs = reservoir(
        sandface_in=Stream(
            m_dot=Quantity(inputs["flow"] * 1000, "kg/s"),
            T=Quantity(300, "K"),
            p=Quantity(23e6, "Pa"),
        )
    ).outputs
    return dict(bottomhole_pressure=outputs.bottomhole_pressure)


def _production_ipr(inputs):
    """Evaluate the production inflow performance at one withdrawal rate."""
    reservoir = configured(ProductionReservoir, _reservoir_parameters())
    outputs = reservoir(production_rate=inputs["flow"] * 1000).outputs
    return dict(bottomhole_pressure=outputs.bottomhole_pressure)


def _injectivity(inputs):
    """Infer the injectivity index from one measured flow and bottomhole pressure."""
    reservoir = configured(InjectionReservoir, _reservoir_parameters())
    index = reservoir.injectivity_from_measurements(inputs["flow"], inputs["bottomhole_pressure"])
    return dict(injectivity_index=index)


def _reservoir_estimate(inputs):
    """Fit the reservoir pressure line through measured flows and bottomhole pressures."""
    estimate = estimate_reservoir_pressure(inputs["flow"], inputs["bottomhole_pressure"])
    pressure, r_squared = estimate["pressure"]["value"], estimate["r_squared"]["value"]
    return dict(reservoir_pressure=pressure, r_squared=r_squared)


def _reservoir_dp(inputs):
    """Evaluate hydrostatic, skin, flow and radial pressure terms with measured fluid data."""
    parameters = _reservoir_parameters() | dict(skin=inputs["skin_factor"])
    reservoir = configured(ProductionReservoir, parameters)
    reservoir.fluid = Fluid(
        density=Quantity(inputs["density"], "kg/m3"),
        viscosity=Quantity(inputs["viscosity"], "Pa.s"),
    )
    outputs = reservoir(production_rate=inputs["flow"] * inputs["density"]).outputs
    return dict(
        Hydrostatic_dp=outputs.hydrostatic_pressure_drop,
        skin_pressure_drop=outputs.skin_pressure_drop,
        bottomhole_dp=outputs.flow_pressure_drop,
        reservoir_dp=outputs.radial_bottomhole_pressure,
    )


RESERVOIR_CASES = {
    "ipr_injection": _injection_ipr,
    "ipr_production": _production_ipr,
    "injectivity": _injectivity,
    "reservoir_estimate": _reservoir_estimate,
    "reservoir_dp": _reservoir_dp,
}


def _pipe_path(parameters):
    """Build the captured trajectory from per-section length, angle, diameter and roughness."""
    return geometry.PipePath(
        sections=[
            geometry.PipeSection(
                length=length,
                inclination=inclination,
                inner_diameter=diameter,
                roughness=roughness,
            )
            for length, inclination, diameter, roughness in zip(
                parameters["length"],
                parameters["angle"],
                parameters["diameter"],
                parameters["roughness"],
            )
        ]
    )


def _well(is_production, parameters, inputs):
    """March one well from its inlet end and report the outlet state and pressure terms."""
    module_class, inlet, outlet = (
        (ProductionWell, "bottom_in", "wellhead_out")
        if is_production
        else (InjectionWell, "wellhead_in", "bottom_out")
    )
    well = configured(
        module_class,
        dict(
            **geometry.section_values(_pipe_path(parameters)),
            soil_temperature=inputs["temperature_ambient"],
            **WELL,
            **({"segment": "full"} if is_production else {}),
        ),
    )
    stream = Stream(
        m_dot=Quantity(inputs["flowrate"] * 1000, "kg/s"),
        p=Quantity(inputs["pressure"], "Pa"),
        T=Quantity(inputs["temperature"], "K"),
    )
    evaluated = well(**{inlet: stream})
    outputs, outlet_stream = evaluated.outputs, evaluated.outlets[outlet]
    return dict(
        pressure_output=outlet_stream.p,
        temperature_output=outlet_stream.T,
        pressuredrop_fric_output=outputs.friction_pressure_drop,
        pressuredrop_grav_output=outputs.gravity_pressure_drop,
        section_pressure_output=outputs.section_pressure,
        section_temperature_output=outputs.section_temperature,
    )


def _temperature_change(inputs):
    """Call the pipe temperature correlation with the captured positional input order."""
    return heat_transfer.pipe_temperature_change(
        inputs[0], inputs[1], inputs[6], inputs[2], inputs[3], inputs[4], inputs[5], inputs[7]
    )


def _corrosion(is_fitted, parameters, inputs):
    """Evaluate one CO2 corrosion model from captured laboratory units."""
    rate = corrosion.co2_corrosion_rate(
        parameters["corrosion_model"],
        fitted=is_fitted,
        temperature=units.c_to_k(inputs["temperature"]),
        pressure=units.bar_to_pa(inputs["pressure"]),
        water_flow_rate=inputs["flow_rate"],
        water_density=inputs["water_density"],
        water_viscosity=units.cp_to_pas(inputs["water_viscosity"]),
        diameter=parameters["diameter"],
        roughness=parameters["roughness"],
        co2_fraction=inputs["co2_fraction"],
        bicarb_concentration=inputs["bicarb_concentration"] / units.KILO,
        ionic_strength=inputs["ionic_strength"],
    )
    return dict(corrosion_rate=rate)


def _co2_partial_pressure(inputs):
    """Evaluate the CO2 partition from captured laboratory units; report bar."""
    pressure = chemistry.co2_partial_pressure(
        co2_fraction=inputs["co2_mol_fraction"],
        gas_pressure=units.bar_to_pa(inputs["gas_pressure"]),
        gas_water_ratio=inputs["gas_water_ratio"],
        gas_density=inputs["gas_density"],
        gas_molecular_weight=inputs["gas_molecular_weight"] / 1000,
        temperature_sample=units.c_to_k(inputs["temperature_sample"]),
        temperature_system=units.c_to_k(inputs["temperature_system"]),
    )
    return {"CO2 Partial Pressure [bar]": units.pa_to_bar(pressure)}


def _erosion(model, inputs):
    """Return the API erosional velocity or another model's erosion rate; the other is None."""
    if model == "API":
        velocity = erosion.api_erosional_velocity(inputs["rho_fluid"])
        return dict(erosion_rate_mm_yr=None, erosion_velocity_ms=velocity)
    rate = erosion.erosion_rate(
        model,
        flow_rate=units.m3h_to_m3s(inputs["flowRate"]),
        rho_fluid=inputs["rho_fluid"],
        diameter=inputs["diameter"],
    )
    return dict(erosion_rate_mm_yr=rate, erosion_velocity_ms=None)
