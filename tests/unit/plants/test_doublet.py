"""The reusable doublet produces through its upper limb and injects through its lower limb."""

import json
import math

import pytest

import gemini as gm
from gemini import units
from gemini.physics import constants
from gemini.types import Stream
from tests.fixtures.balance import assert_plant_closes
from tests.fixtures.reading import reading


@pytest.fixture
def doublet(fresh_plant):
    """Return the example doublet with its production controls set."""
    module = fresh_plant.doublet
    module._set_inputs({"reservoir.production_rate": 40.0, "esp.frequency": 50.0})
    return module


def test_supply_is_the_riser_wellhead_and_return_reaches_the_sink(doublet):
    """Both limbs run once; electricity and heat loss sum over every leaf call."""
    returned = Stream(m_dot=40, T=330, p=5e6, fluid=doublet.fluid)
    result = doublet(return_in=returned)
    leaves = result.leaves()
    assert result.outlets.supply_out == leaves["riser"].outlets.wellhead_out
    assert leaves["injector"].inlets.wellhead_in == returned
    assert leaves["sink"].inlets.sandface_in == leaves["injector"].outlets.bottom_out
    electricity = sum(reading(leaf).get("electricity", 0.0) for leaf in leaves.values())
    assert reading(result).electricity == pytest.approx(electricity)
    lossy = [leaf for leaf in leaves.values() if "loss_out" in leaf.outlets]
    heat_loss = sum(leaf.outlets.loss_out for leaf in lossy)
    assert sum(leaves["formation"].inlets.heat_in) == pytest.approx(heat_loss)
    assert_plant_closes(doublet, result)


DESIGN = {
    "depth": "2500 m",
    "gradient": "30 K/km",
    "surface_temperature": "12 degC",
    "permeability": "200 mD",
    "thickness": "100 m",
    "well_diameter": "0.244 m",
}
PUMP = {
    "nominal_flow": "300 m3/h",
    "pump_efficiency": 0.7,
    "nominal_wellhead_pressure": "10 bar",
}
BRINE = gm.Fluid(density="1030 kg/m3", viscosity="0.4 mPa*s")


def designed(**extra):
    """Return a doublet in a plant, designed from its depth, in a brine of 1030 kg/m3."""
    plant = gm.Plant("Holder")
    doublet = plant.add("Doublet", name="d0", params=DESIGN | extra)
    plant.connect("return_in", "d0.return_in")
    plant.connect("power_in", "d0.power_in")
    plant.connect("d0.supply_out", "supply_out")
    doublet.fluid = BRINE
    return plant, doublet


def test_the_reservoir_comes_from_the_depth():
    """87 degC, and 252.6 bar(g) of hydrostatic brine at the 2 500 m midpoint."""
    _, doublet = designed()
    assert doublet.reservoir.temperature == pytest.approx(360.15)
    assert doublet.sink.temperature == pytest.approx(360.15)
    assert doublet.reservoir.pressure == pytest.approx(1030 * 9.81 * 2500 + 101325)
    assert units.convert(doublet.reservoir.pressure, "Pa", "bar(g)") == pytest.approx(252.6, 0.01)


def test_the_productivity_index_is_radial_darcy():
    """12.39 m3/h/bar for 200 mD, 100 m and a 0.244 m well, from a hand calculation."""
    _, doublet = designed()
    k_h = 200 * 9.869233e-16 * 100
    expected = 2 * math.pi * k_h / (4e-4 * math.log(1000 / 0.122))
    assert doublet.reservoir.productivity_index == pytest.approx(expected)
    assert doublet.sink.injectivity_index == pytest.approx(expected)
    assert units.convert(expected, "m3/s/Pa", "m3/h/bar") == pytest.approx(12.386, abs=1e-3)


def test_the_wells_are_vertical_paths():
    """Both wells reach the depth at the diameter; the soil is the geotherm at half depth."""
    _, doublet = designed()
    for well in (doublet.well, doublet.riser, doublet.injector):
        (section,) = well.pipe_path.sections
        assert section.length == 2500 and section.inner_diameter == 0.244
        assert section.inclination == pytest.approx(math.pi / 2)
        assert well.soil_temperature == pytest.approx(322.65)


def test_the_skin_of_a_reservoir_enters_its_index():
    """A larger skin lowers the index of that reservoir only."""
    _, clean = designed()
    _, skinned = designed(**{"reservoir.skin": 5.0})
    assert skinned.reservoir.productivity_index < clean.reservoir.productivity_index
    assert skinned.sink.injectivity_index == clean.sink.injectivity_index


def test_an_explicit_child_value_wins_over_the_derived_one():
    """A stated pressure and pipe path stay, and the pump is sized on the stated pressure."""
    path = {
        "sections": [
            {"length": 2600.0, "inclination": 1.0, "inner_diameter": 0.2, "roughness": 1e-5}
        ]
    }
    _, doublet = designed(**{"reservoir.pressure": "250 bar(g)", "well.pipe_path": path} | PUMP)
    assert doublet.reservoir.pressure == pytest.approx(250e5 + 101325)
    assert doublet.well.pipe_path.total_length == 2600
    assert doublet.riser.pipe_path.total_length == 2500
    _, derived = designed(**PUMP)
    assert doublet.esp.head_coefficients[0] > derived.esp.head_coefficients[0]


def test_the_pump_is_sized_at_its_nominal_flow():
    """The pump keeps the wellhead pressure at the nominal flow, with its efficiency."""
    plant, doublet = designed(**PUMP)
    flow = 300 / 3600
    plant._set_inputs(
        {
            "d0.reservoir.production_rate": flow * 1030,
            "d0.esp.frequency": constants.ESP_REFERENCE_FREQUENCY,
        }
    )
    returned = gm.Stream(m_dot=flow * 1030, T=320, p=5e6, fluid=BRINE)
    result = plant(return_in=returned)
    assert result.outlets.supply_out.p == pytest.approx(10e5, rel=2e-2)
    esp = reading(result.leaves()["d0.esp"])
    hydraulic = esp.flow * esp.head
    assert esp.electricity == pytest.approx(hydraulic / 0.7, rel=1e-6)
    assert doublet.esp.setting_depth == doublet.well.esp_depth == doublet.riser.esp_depth
    assert 0 < doublet.esp.setting_depth < 2500


def test_setting_the_fluid_derives_again():
    """Pressure and index follow a fluid set after the design."""
    _, doublet = designed()
    doublet.fluid = gm.Fluid(density=1000.0, viscosity=8e-4)
    assert doublet.reservoir.pressure == pytest.approx(1000 * 9.81 * 2500 + 101325)
    assert doublet.reservoir.fluid.density == 1000
    assert doublet.sink.fluid.viscosity == 8e-4


def test_the_file_holds_the_design_and_rebuilds_the_same_numbers():
    """No derived value is written, and reading derives the same ones."""
    plant, doublet = designed(**PUMP | {"reservoir.skin": 2.0})
    spec = plant.to_dict()
    params = spec["modules"]["d0"]["params"]
    assert params == DESIGN | PUMP | {"reservoir.skin": 2.0}
    rebuilt = gm.Plant.from_dict(json.loads(json.dumps(spec))).d0
    assert rebuilt.reservoir.productivity_index == doublet.reservoir.productivity_index
    assert rebuilt.reservoir.pressure == doublet.reservoir.pressure
    assert rebuilt.esp.head_coefficients == doublet.esp.head_coefficients
    assert rebuilt.well.pipe_path == doublet.well.pipe_path


def test_a_designed_doublet_as_the_root_round_trips():
    """A doublet stores its class and its flat design, never its structure."""
    doublet = gm.plants.get("Doublet")
    assert doublet.to_dict()["params"] == {} and "modules" not in doublet.to_dict()
    doublet.set_params("", DESIGN)
    spec = doublet.to_dict()
    assert spec["type"] == "Doublet" and spec["params"] == DESIGN
    assert gm.Plant.from_dict(spec).reservoir.temperature == pytest.approx(360.15)


def test_a_dated_design_derives_at_its_date():
    """A deeper design from a date on gives its temperature from that date on."""
    plant, _ = designed()
    plant.set_params("d0", {"depth": "3000 m"}, valid_from="2030-01-01")
    assert plant.params_at("d0.reservoir", "2031-01-01")["temperature"] == pytest.approx(375.15)
    assert plant.params_at("d0.reservoir", "2029-01-01")["temperature"] == pytest.approx(360.15)


def test_a_waiting_depth_is_a_missing_parameter():
    """``missing_parameters`` names the geotherm, and a doublet without a depth needs none."""
    doublet = gm.plants.Doublet().set_params("", {"depth": "2500 m"})
    assert doublet.missing_parameters()[:2] == ["gradient", "surface_temperature"]
    assert "gradient" not in gm.plants.Doublet().missing_parameters()


def test_a_depth_waits_for_its_geotherm():
    """A plant may hold the design and a problem the site: nothing is derived until both exist."""
    doublet = gm.plants.Doublet().set_params("", {"depth": "2500 m", "gradient": "30 K/km"})
    assert doublet.get_submodule("reservoir")._params_at(None).get("temperature") is None
    doublet.set_params("", {"surface_temperature": "12 degC"})
    assert doublet.reservoir.temperature == pytest.approx(285.15 + 75)


def test_the_values_of_a_stored_doublet_rebuild_in_any_order():
    """The depth before its geotherm in a plant dict is read like the geotherm before the depth."""
    plant, _ = designed()
    spec = plant.to_dict()
    params = spec["modules"]["d0"]["params"]
    spec["modules"]["d0"]["params"] = dict(reversed(list(params.items())))
    assert gm.Plant.from_dict(spec).d0.reservoir.temperature == pytest.approx(360.15)
    spec["modules"]["d0"]["params"] = params
    assert gm.Plant.from_dict(spec).d0.reservoir.temperature == pytest.approx(360.15)


def test_the_old_way_keeps_working(fresh_plant):
    """A doublet set child by child has no design and derives nothing."""
    assert fresh_plant.doublet.depth is None
    assert fresh_plant.doublet.reservoir.pressure == 22000000.0


def test_the_volume_imbalance_of_a_balanced_doublet_is_zero():
    """Produced and injected liquid at one density: the gas leaves in between, the liquid stays."""
    doublet = gm.plants.Doublet()
    doublet.fluid = gm.Fluid(
        density=1030,
        viscosity="0.4 mPa*s",
        gas_liquid_ratio=0.8,
        gas_composition={"CH4": 0.8, "CO2": 0.2},
    )
    doublet.set_params("", DESIGN | PUMP)
    doublet.reservoir.production_rate = 80.0
    doublet.esp.frequency = "60 Hz"
    liquid = doublet.fluid.with_gas_fraction(0.0)
    produced = doublet.fluid.properties(0, 0)
    injected = gm.Stream(m_dot=80.0 * (1 - produced.gmf), T=320.0, p=5e6, fluid=liquid)
    outputs = doublet(return_in=injected).outputs
    assert outputs.volume_imbalance == pytest.approx(0, abs=1e-14)


def test_the_volume_imbalance_is_produced_less_injected():
    """Less injected than produced is a positive imbalance."""
    doublet = gm.plants.Doublet()
    doublet.fluid = gm.Fluid(density=1030, viscosity="0.4 mPa*s")
    doublet.set_params("", DESIGN | PUMP)
    doublet.reservoir.production_rate = 80.0
    doublet.esp.frequency = "60 Hz"
    injected = gm.Stream(m_dot=70.0, T=320.0, p=5e6, fluid=doublet.fluid)
    assert doublet(return_in=injected).outputs.volume_imbalance == pytest.approx(10 / 1030)
