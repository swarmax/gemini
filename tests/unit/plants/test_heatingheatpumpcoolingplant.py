"""The class of the HeatingHeatPumpCoolingPlant: its example validates and rebuilds."""

import gemini as gm
from tests.fixtures.sample_cases import template_plant


def test_the_example_is_complete_and_rebuilds():
    """Every port is connected, and the plant dict gives the same plant."""
    plant = template_plant("HeatingHeatPumpCoolingPlant")
    assert plant.is_initialized
    assert gm.plants.validate(plant.to_dict(structure=True), on_error="record") == []
    assert gm.Plant.from_dict(plant.to_dict()).to_dict() == plant.to_dict()
