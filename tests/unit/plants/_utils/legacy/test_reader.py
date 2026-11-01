"""Converting an old project folder to a plant spec."""

import gemini as gm
from gemini.plants._utils.legacy import reader as legacy_project
from tests.fixtures import OLD_PROJECT
from tests.fixtures.errors import raises
from tests.fixtures.sample_cases import example_plant


def test_the_example_project_converts_to_the_shared_plant_file():
    """The old example project gives the spec of the shared doublet heat plant, exactly."""
    spec = legacy_project.from_folder(OLD_PROJECT).to_dict()
    assert spec == example_plant("DoubletHeatPlant").to_dict()
    assert gm.plants.validate(spec) == []
    assert gm.Plant.from_dict(spec).to_dict() == spec


def test_the_public_name_gives_the_same_plant():
    """``gm.Plant.from_legacy`` reads the folder this function reads."""
    plant = gm.Plant.from_legacy(OLD_PROJECT)
    assert plant.to_dict() == legacy_project.from_folder(OLD_PROJECT).to_dict()


def test_a_folder_without_a_diagram_is_a_legacy_format_error(tmp_path):
    """A folder that is not an old project raises the legacy error, naming the missing file."""
    with raises(gm.errors.ValidationError, "invalid_format", match="diagram"):
        legacy_project.from_folder(tmp_path)
