"""``BoilerChpPlant``: the upstream ``doublet_plant`` example with a boiler and a CHP."""

import pytest

import gemini as gm
from tests.fixtures.sample_cases import example_plant

SECONDARY = gm.Stream(
    flow={"value": 140, "unit": "m3/h"},
    T={"value": 20, "unit": "degC"},
    p={"value": 3, "unit": "bar"},
    fluid=gm.Fluid(kind="water"),
)
GAS_FACTOR = 56.6 / 1e9
GRID_FACTOR = 0.3 / 3.6e6
INPUTS = {
    "doublet.esp.frequency": {"value": 65, "unit": "Hz"},
    "doublet.wellhead_pressure": {"value": 3, "unit": "bar"},
    "splitter.split_fraction": 0.5,
    "boiler.temperature_setpoint": {"value": 70, "unit": "degC"},
    "chp.load_fraction": 1.0,
    "air.temperature": {"value": 10, "unit": "degC"},
}


@pytest.fixture(scope="module")
def run():
    """Return the example plant and one call of it."""
    plant = example_plant("BoilerChpPlant")
    plant._set_inputs(INPUTS)
    return plant, plant(return_in=SECONDARY)


def test_the_call_reproduces_the_case(run):
    """The solved rate, the duty, the mixed outlet and the energy flows of the case."""
    _, result = run
    flows = gm.modules.collect_flows(result)
    assert round(result.children["doublet.riser"].outlets.wellhead_out.m_dot * 3.6, 2) == 129.02
    assert round(result.children["heat_exchanger"].outputs.get("duty", unit="MW"), 3) == 3.961
    assert round(gm.units.convert(result.outlets.supply_out.T, "K", "degC"), 2) == 47.74
    assert round(flows["fuel"] / 1e6, 3) == 1.174
    assert round(flows["electricity_generated"] / 1e6, 3) == 0.400


def test_the_injector_needs_no_pump(run):
    """The 3100 m column over-delivers, so the injection pump draws nothing."""
    assert run[1].children["doublet.injection_pump"].outputs.power == 0


def test_the_call_closes(run):
    """Every balance of the plant closes."""
    plant, result = run
    assert all(check["passed"] for check in gm.evaluate.plant_balance(plant, None, result))


def test_the_emissions_charge_the_fuel_and_the_grid_electricity(run):
    """The case emits 5742 kg of CO2 a day at 56.6 kg/GJ of gas and 0.3 kg/kWh of grid power."""
    _, result = run
    assert round(gm.modules.emissions(result, GAS_FACTOR, GRID_FACTOR) * 86400) == 5742
