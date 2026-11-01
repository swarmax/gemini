"""Mass and energy close for every shipped plant and every module in it, on a run."""

import pytest

import gemini as gm
from tests.fixtures.balance import assert_plant_closes
from tests.fixtures.doublet_day import doublet_day
from tests.fixtures.heating_cooling import two_days_case
from tests.fixtures.sample_cases import template_plant

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
    clock, plan = doublet_day(frequency)
    results = gm.simulate(plant, plan=plan, clock=clock)
    assert_plant_closes(plant, results)
