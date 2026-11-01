"""Mass and energy close for every shipped plant and every module in it, on a run."""

import pytest

import gemini as gm
from tests.fixtures.balance import assert_plant_closes
from tests.fixtures.heating_cooling import two_days_case
from tests.fixtures.sample_problems import template_plant

pytestmark = pytest.mark.e2e
PLANTS = (
    "HeatingPlant",
    "HeatingAbsorptionCoolingPlant",
    "HeatingHeatPumpCoolingPlant",
    "HeatingFullCoolingPlant",
    "HeatingCoolingPlant",
)


@pytest.mark.parametrize("name", PLANTS)
def test_a_heating_and_cooling_plant_closes(name):
    """The root's in and out are the ports of its grids, its air and its aquifers."""
    plant = template_plant(name)
    results = gm.simulate(plant, plan=gm.schedule(plant, two_days_case()), on_error="raise")
    assert_plant_closes(plant, results)


@pytest.mark.parametrize("frequency", [55, 60, 65])
def test_the_doublet_heat_plant_closes(frequency):
    """A simulated day of the shipped example closes tick by tick."""
    plant = gm.plants.example("DoubletHeatPlant")
    clock = gm.engine.Clock.days(2027, 1, 1, days=1)
    profiles = {
        "doublet.reservoir.production_rate": gm.types.Profile.constant(
            150, unit="m3/h", clock=clock
        ),
        "doublet.esp.frequency": gm.types.Profile.constant(frequency, unit="Hz", clock=clock),
        "injection_pump.pressure_setpoint": gm.types.Profile.constant(
            51.5, unit="bar", clock=clock
        ),
    }
    results = gm.simulate(plant, plan=gm.Dataset.from_profiles(profiles), clock=clock)
    assert_plant_closes(plant, results)
