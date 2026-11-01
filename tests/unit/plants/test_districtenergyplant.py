"""``DistrictEnergyPlant``: a heating network and an ATES-cooled cooling network."""

import pytest

import gemini as gm
from tests.fixtures.sample_cases import example_plant

COOLING = "cooling.substations.0"
INPUTS = {
    "heating.pump.frequency": {"value": 50, "unit": "Hz"},
    "heating.splitters.0.split_fraction": 0.5,
    "heating.substations.0.valve.opening": 0.9,
    "heating.substations.1.valve.opening": 0.9,
    "heating.substations.0.consumer.heat_demand": {"value": 150, "unit": "kW"},
    "heating.substations.1.consumer.heat_demand": {"value": 100, "unit": "kW"},
    "cooling.pump.frequency": {"value": 50, "unit": "Hz"},
    f"{COOLING}.valve.opening": 0.9,
    f"{COOLING}.consumer.sensible_cooling_demand": {"value": 150, "unit": "kW"},
    f"{COOLING}.consumer.latent_cooling_demand": {"value": 0, "unit": "kW"},
    f"{COOLING}.consumer.indoor_temperature": {"value": 24, "unit": "degC"},
    f"{COOLING}.consumer.indoor_relative_humidity": 0.5,
    "ates.storage.groundwater_flow": {"value": 36, "unit": "t/h"},
    "ates.storage.mode": "charge",
    "ates.source_valve.split_fraction": 0.0,
    "ates.load_valve.split_fraction": 0.0,
    "ates.pump.frequency": {"value": 50, "unit": "Hz"},
    "ates.heat_pump.temperature_setpoint": {"value": 40, "unit": "degC"},
    "air.temperature": {"value": 10, "unit": "degC"},
}


@pytest.fixture(scope="module")
def run():
    """Return the example plant and two hourly steps, the return fed back."""
    plant = example_plant("DistrictEnergyPlant")
    plant._set_inputs(INPUTS)
    inlets = {
        "hot_in": gm.Stream(
            flow={"value": 18, "unit": "t/h"},
            T={"value": 75, "unit": "degC"},
            p={"value": 6, "unit": "bar"},
        ),
        "cold_in": gm.Stream(
            flow={"value": 36, "unit": "t/h"},
            T={"value": 17, "unit": "degC"},
            p={"value": 3, "unit": "bar"},
        ),
        "air_in": gm.modules.Atmosphere.ambient_air({"value": 10, "unit": "degC"}),
    }
    state, first = plant.step(None, 3600, inlets)
    state, second = plant.step(state, 3600, inlets | {"cold_in": first.outlets.cold_out})
    return plant, first, second


def test_the_store_charges_step_by_step(run):
    """The stored energy starts at zero and grows with the warmed groundwater."""
    _, first, second = run
    assert first.children["ates"].children["storage"].outputs.stored_energy == 0
    assert (
        round(second.children["ates"].children["storage"].outputs.stored_energy / 3.6e9, 3) == 0.228
    )


def test_the_chilled_water_follows_the_returned_water(run):
    """The first step uses the given return, the second what the network gave back."""
    _, first, second = run
    assert round(first.children["ates"].outlets.supply_out.T - 273.15, 2) == 11.59
    assert round(second.children["ates"].outlets.supply_out.T - 273.15, 2) == 11.41


def test_every_step_closes(run):
    """Every balance of the plant closes on each step."""
    plant, first, second = run
    for result in (first, second):
        assert all(check["passed"] for check in gm.evaluate.plant_balance(plant, None, result))
