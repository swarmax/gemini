"""``ParallelExchangerPlant``: the upstream ``parallel_hex_plant`` example."""

import pytest

import gemini as gm
from tests.fixtures.sample_cases import example_plant

SECONDARY = gm.Stream(
    flow={"value": 125.1, "unit": "m3/h"},
    T={"value": 20, "unit": "degC"},
    p={"value": 3, "unit": "bar"},
    fluid=gm.Fluid(kind="water"),
)
FITTED_INJECTION = gm.Stream(
    flow={"value": 125.1, "unit": "m3/h"},
    T={"value": 70, "unit": "degC"},
    p={"value": 44.47, "unit": "bar"},
)
INPUTS = {
    "doublet.esp.frequency": {"value": 60, "unit": "Hz"},
    "doublet.wellhead_pressure": {"value": 10, "unit": "bar"},
    "primary_splitters.0.split_fraction": 0.5,
    "primary_splitters.1.split_fraction": 0.6,
    "secondary_splitters.0.split_fraction": 0.5,
    "secondary_splitters.1.split_fraction": 0.6,
}


@pytest.fixture(scope="module")
def run():
    """Return the example plant and one call of it."""
    plant = example_plant("ParallelExchangerPlant")
    plant._set_inputs(INPUTS)
    return plant, plant(return_in=SECONDARY)


def test_the_call_reproduces_the_upstream_case(run):
    """The rate, the injection and the three duties of the upstream example."""
    _, result = run
    pump = result.children["doublet.injection_pump"].outputs
    assert round(result.children["doublet.riser"].outlets.wellhead_out.m_dot * 3.6, 2) == 125.10
    assert round(pump.get("discharge_pressure", unit="bar"), 2) == 54.86
    assert round(pump.get("power", unit="kW"), 1) == 195.6
    duties = [result.children[f"heat_exchangers.{index}"].outputs.duty for index in range(3)]
    assert [round(duty / 1e3, 1) for duty in duties] == [297.8, 178.7, 119.1]
    assert round(gm.units.convert(result.outlets.supply_out.T, "K", "degC"), 2) == 24.06


def test_the_shares_divide_both_streams(run):
    """Each exchanger sees its 50/30/20 share of the two flows."""
    _, result = run
    hot = [result.children[f"heat_exchangers.{index}"].inlets.hot_in.m_dot for index in range(3)]
    assert [flow / sum(hot) for flow in hot] == pytest.approx([0.5, 0.3, 0.2])


def test_the_call_closes(run):
    """Mass, the thermal audit and every balance of the plant close."""
    plant, result = run
    assert gm.modules.mass_balance(plant, result)["residual"] == 0
    assert gm.modules.energy_balance(plant, result)["relative_thermal_residual"] < 1e-9
    assert all(check["passed"] for check in gm.evaluate.plant_balance(plant, None, result))


def test_a_recalibrated_injectivity_reproduces_the_fitted_injection():
    """The index fitted to 44.47 bar at 125.1 m3/h gives that pressure and a smaller pump."""
    plant = example_plant("ParallelExchangerPlant")
    plant._set_inputs(INPUTS)
    doublet = plant.doublet
    bottom = doublet.injector(wellhead_in=FITTED_INJECTION).outlets.bottom_out
    flow = abs(bottom.m_dot) / doublet.sink.fluid.properties(bottom.p, bottom.T).rho_l
    index = doublet.sink.injectivity_from_measurements(flow, bottom.p)
    doublet.sink.set_params("", {"injectivity_index": gm.units.Quantity(index, "m3/s/Pa")})
    outputs = plant(return_in=SECONDARY).children["doublet.injection_pump"].outputs
    assert round(gm.units.convert(index, "m3/s/Pa", "m3/h/bar"), 4) == 2.843
    assert round(outputs.get("discharge_pressure", unit="bar"), 2) == 44.47
    assert round(outputs.get("power", unit="kW"), 1) == 150.5
