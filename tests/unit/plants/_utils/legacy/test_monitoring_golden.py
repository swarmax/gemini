"""Reproduce the eight captured historical monitoring outputs from the old project files.

``runtime_values.json`` holds values produced by the old monitoring runtime. They are rebuilt
through public equipment models from the old ``.param`` files and the second row of the old
semicolon CSV, including the documented arithmetic quirks of that runtime. The test lives with
the legacy tests because it reads old formats through ``gemini.plants._utils.legacy.tables``.
"""

import json
import math

import numpy as np
import pandas as pd

import gemini as gm
from gemini import units
from gemini.modules.pumps import ESP
from gemini.modules.subsurface import InjectionReservoir, ProductionReservoir
from gemini.modules.wells import InjectionWell, ProductionWell
from gemini.physics import geometry
from gemini.plants._utils.legacy import tables
from gemini.types.flows import Stream
from tests.fixtures import FIXTURES, OLD_PROJECT
from tests.fixtures.evaluate import assert_values, configured
from tests.fixtures.reading import reading


def _old_property(name):
    """Read the first-timestamp property block of one old ``.param`` file."""
    return tables.from_property(OLD_PROJECT / (name + ".param"))


def _esp_theoretical_values(row, esp_property):
    """Evaluate the ESP curve in float32, as the old runtime did, and report bar."""
    pump = configured(ESP, tables.esp_params_from_gemini(esp_property))
    with gm.runtime.settings(precision="float32"):
        outputs = reading(
            pump(
                frequency=row.ESP_freq,
                fluid_in=Stream(
                    m_dot=units.m3h_to_m3s(row.Qp) * 1000,
                    T=300,
                    p=units.bar_to_pa(row.ESP_Pin),
                ),
            )
        )
    head = float(units.pa_to_bar(np.float32(outputs.head)))
    return {
        "esp_1ee3:esp_theoretical_head.calculated": [head],
        "esp_1ee3:esp_theoretical_power.calculated": [outputs.power],
        "esp_1ee3:esp_theoretical_outlet_pressure.calculated": [head + row.ESP_Pin],
    }


def _historical_ipr_parameters(reservoir_property, well_property):
    """Return production reservoir parameters with the historical productivity unit.

    NOTE(refactor): historical IPR interpreted the labelled m3/h/bar value as m3/s/bar.
    """
    parameters = tables.production_reservoir_params_from_gemini(reservoir_property, well_property)
    parameters["productivity_index"] = units.pa_to_bar(
        well_property["productionwell_productivity_index"]
    )
    return parameters


def _historical_production_path(well_property, esp_property):
    """Return the trajectory the old runtime used for the production well.

    NOTE(refactor): golden-only reconstruction omits the old ESP-crossing interval and uses one
    vertical tubing segment above the pump. Production graphs use the full path.
    """
    table = well_property["productionwell_trajectory_table"]
    full = geometry.build_path(table)
    below = [
        section
        for point, section in zip(table, full.sections)
        if point["MD"] >= esp_property["esp_depth"]
    ]
    top = geometry.PipeSection(
        length=esp_property["esp_depth"],
        inclination=math.pi / 2,
        inner_diameter=esp_property["esp_tubing"],
        roughness=table[1]["roughness"],
    )
    return geometry.PipePath(sections=[top, *below])


def _esp_vlp_values(row, well_property, esp_property, reservoir_property):
    """Infer ESP intake and corrected outlet pressure from the reservoir and wellhead sides."""
    reservoir_parameters = _historical_ipr_parameters(reservoir_property, well_property)
    reservoir = configured(ProductionReservoir, reservoir_parameters)
    reservoir.fluid = tables.reservoir_fluid(reservoir_property)
    well_parameters = tables.productionwell_params_from_gemini(
        well_property, esp_property=esp_property
    )
    well_parameters["pipe_path"] = _historical_production_path(well_property, esp_property)
    well = configured(ProductionWell, well_parameters)
    well.fluid = reservoir.fluid
    density = reservoir.fluid.properties(
        reservoir_parameters["pressure"], reservoir_parameters["temperature"]
    ).rho_l
    mass = units.m3h_to_m3s(row.Qp) * density
    intake = well.intake_conditions(reservoir(production_rate=mass).outlets["sandface_out"])
    wellhead = Stream(
        m_dot=mass, p=units.bar_to_pa(row.Pwh_prod), T=units.c_to_k(row.T_p_in), fluid=well.fluid
    )
    discharge = well.discharge_from_wellhead(wellhead)
    slope, offset = tables.esp_params_from_gemini(esp_property)["correction_factors"]
    outlet_pressure = units.pa_to_bar(slope * discharge.p + offset)
    return {
        "esp_1ee3:esp_vlp_ipr_inlet_pressure.calculated": [units.pa_to_bar(intake.p)],
        "esp_1ee3:esp_vlp_outlet_pressure.calculated": [outlet_pressure],
        "esp_1ee3:esp_vlp_head.calculated": [outlet_pressure - row.ESP_Pin],
    }


def _injection_values(row):
    """Infer injection bottomhole pressure and injectivity from the injector wellhead."""
    well_property = _old_property("injection_well_a06b")
    reservoir_property = _old_property("reservoir_28fc")
    reservoir = configured(
        InjectionReservoir,
        tables.injection_reservoir_params_from_gemini(reservoir_property, well_property),
    )
    reservoir.fluid = tables.reservoir_fluid(reservoir_property)
    well = configured(InjectionWell, tables.injectionwell_params_from_gemini(well_property))
    well.fluid = reservoir.fluid
    pressure, temperature = units.bar_to_pa(row.InjectorPump_Pout), units.c_to_k(row.T_p_out)
    wellhead = Stream(
        m_dot=-units.m3h_to_m3s(row.Qp) * well.fluid.properties(pressure, temperature).rho_l,
        p=pressure,
        T=temperature,
        fluid=well.fluid,
    )
    outputs = reading(well(wellhead_in=wellhead))
    injectivity = reservoir.injectivity_from_measurements(
        units.m3h_to_m3s(row.Qp), outputs.bottomhole_pressure
    )
    return {
        "injection_well_a06b:injectionwell_bottomhole_pressure.calculated": [
            units.pa_to_bar(outputs.bottomhole_pressure)
        ],
        "injection_well_a06b:injectionwell_injectivity_index.calculated": [
            units.index_from_si(injectivity)
        ],
    }


def test_captured_monitoring_values():
    """Reproduce all eight immutable historical outputs, including documented arithmetic quirks."""
    row = pd.read_csv(OLD_PROJECT / "doublet_2024_old.csv", sep=";").iloc[1]
    well_property = _old_property("production_well_c774")
    esp_property = _old_property("esp_1ee3")
    reservoir_property = _old_property("reservoir_c1b5")
    actual = (
        _esp_theoretical_values(row, esp_property)
        | _esp_vlp_values(row, well_property, esp_property, reservoir_property)
        | _injection_values(row)
    )
    expected = json.loads((FIXTURES / "runtime_values.json").read_text())
    assert_values(actual, expected)
