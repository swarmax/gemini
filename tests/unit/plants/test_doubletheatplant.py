"""The class of the DoubletHeatPlant: its example validates and rebuilds."""

import gemini as gm
from tests.fixtures.sample_cases import example_plant


def test_the_example_is_complete_and_valid():
    """Every port is connected and every parameter has a value."""
    plant = example_plant("DoubletHeatPlant")
    assert plant.is_initialized
    assert gm.plants.validate(plant.to_dict(structure=True), on_error="record") == []
