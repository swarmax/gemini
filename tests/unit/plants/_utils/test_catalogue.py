"""The plant catalogue: names and new plants."""

import hashlib
import json

import pytest

import gemini as gm
from gemini.plants._utils import catalogue
from tests.fixtures.errors import raises
from tests.fixtures.sample_cases import example_plant, treatment_plant

TEMPLATE_PLANTS = (
    "HeatingPlant",
    "HeatingCoolingPlant",
    "HeatingFullCoolingPlant",
    "HeatingAbsorptionCoolingPlant",
    "HeatingHeatPumpCoolingPlant",
)
"""The plants whose values are the sample problem's, in ``inputs/examples/``, not an example."""
FORMER_EXAMPLES = {
    "ATESPlant": "6a0269fce3fa75cb6309b11779cad3ac605aa65d5089020cb76ff8aa7e8b8170",
    "BoilerChpPlant": "a53a8beb1708973d3ec2341809dd846ae38c71feda6487585c36f13152da2bb6",
    "CoolingSubstation": "64e2a52f01d79151750d6c90bd03b77ee1fef3e0f18111931cb8dd0cc025e24b",
    "DistrictEnergyPlant": "ebce116425f8cb0bbbb10439e56a05def20c6bb3a9130daf005045042af64095",
    "DistrictNetwork": "d9c9f286535f517fc5b575bd33d2861a5dcf45f65e1d2181c186d412b0c5ed94",
    "Doublet": "5d90cbb7243c9aabe4658a70b11564202a55ae851525265f2669e413467a3038",
    "DoubletHeatPlant": "eeaad3542d83772882955703e94ed0c16b8c2bfbdd22e968bee88b2226c324b4",
    "HeatingSubstation": "4f28ac09ac50639d8f0d3be2dfaf53650cb414105622b4401c27ccbe143eb73c",
    "MultiWellPlant": "46c5098567d2359ab81345d3d9112966977bafea19f93892c0e772dde61da0f7",
    "NodalDoublet": "2b46f6fa46e86e6e0d3053a671768f8f561a21cde20a378310e88af36fee512c",
    "ParallelExchangerPlant": "eeac3836a6bae051c4321d7f09072519cece13fbeaead14146d0ebbb988530c5",
}
"""Hash of ``to_dict()`` of the plant built from each whole example file these values replaced.

The hashes were taken again when the plant dict lost the values of the case and wrote every value
with a unit as ``{"value", "unit"}``; the design values are those of the files.

The template plants have no example: their values are in the sample problem. ``Doublet`` is hashed
without ``outputs``, which its structure file has and its former example file lacked.
"""


def test_names_are_the_registered_plants():
    """Spec plants and the special cases are listed, sorted, and nothing else."""
    assert catalogue.names() == gm.modules.names("plants")
    assert {"Doublet", "DoubletHeatPlant", "MultiWellPlant", "DistrictNetwork"} <= set(
        catalogue.names()
    )
    assert {"HeatingSubstation", "CoolingSubstation", "ATESPlant"} <= set(catalogue.names())
    assert {"NodalDoublet", "ParallelExchangerPlant", "BoilerChpPlant"} <= set(catalogue.names())
    assert {"DistrictEnergyPlant", "HeatingCoolingPlant"} <= set(catalogue.names())
    assert "ESP" not in catalogue.names()


def test_get_returns_a_new_plant_without_values():
    """A spec plant is a Plant, a special case an instance of its class; each call is new."""
    first, second = catalogue.get("Doublet"), catalogue.get("Doublet")
    assert isinstance(first, gm.Plant) and first is not second
    assert isinstance(catalogue.get("HeatingSubstation"), gm.plants.HeatingSubstation)
    assert first.name == "Doublet"


def test_get_refuses_unknown_names_and_modules_that_are_not_plants():
    """An unknown name has close matches; a pump is not a plant."""
    with raises(gm.errors.ValidationError, "unknown_name") as unknown:
        catalogue.get("DubletHeatPlant")
    assert "DoubletHeatPlant" in unknown.value.suggestions
    with raises(gm.errors.ValidationError, "unknown_name"):
        catalogue.get("ESP")


EXAMPLES = [name for name in catalogue.names() if name not in TEMPLATE_PLANTS]


@pytest.mark.parametrize("name", EXAMPLES)
def test_every_spec_plant_and_special_case_has_an_example_that_round_trips(name):
    """An example builds, has no problems and writes the spec it was read from."""
    spec = example_plant(name).to_dict()
    assert gm.plants.validate(spec) == []
    assert gm.Plant.from_dict(spec).to_dict() == spec


@pytest.mark.parametrize("name", EXAMPLES)
def test_every_example_equals_the_plant_of_its_former_file(name):
    """``get`` and the values of ``inputs/plants/`` give the structure and the values pinned."""
    spec = example_plant(name).to_dict(structure=True)
    if name == "Doublet":
        del spec["outputs"]
    text = json.dumps(spec, sort_keys=True)
    assert hashlib.sha256(text.encode()).hexdigest() == FORMER_EXAMPLES[name]


def test_the_doublet_examples_carry_the_shared_doublet_heat_values():
    """The doublet is the ``doublet`` child of the doublet heat plant."""
    shared = example_plant("DoubletHeatPlant").to_dict(structure=True)
    doublet = example_plant("Doublet")
    expected = shared["modules"]["doublet"]["params"]
    assert {
        f"{path}.{name}": value
        for path, entry in doublet.to_dict(structure=True)["modules"].items()
        for name, value in entry["params"].items()
    } == expected


def test_the_other_examples_carry_the_values_of_their_tests(plants):
    """The substations and the network are filled as the unit tests of their folder fill them."""
    heating = plants["heating_substation"](catalogue.get("HeatingSubstation"))
    assert example_plant("HeatingSubstation").state_dict() == heating.state_dict()
    cooling = plants["cooling_substation"](catalogue.get("CoolingSubstation"))
    assert example_plant("CoolingSubstation").state_dict() == cooling.state_dict()
    network = plants["network"](catalogue.get("DistrictNetwork"), plants["heating_substation"])
    assert example_plant("DistrictNetwork").state_dict() == network.state_dict()


def test_a_state_dictionary_fills_a_plant_without_values():
    """A plant from ``get`` has no values and takes those of an example; groups stay groups."""
    example = example_plant("DoubletHeatPlant")
    assert isinstance(example.filters, gm.modules.ModuleDict)
    fresh = catalogue.get("DoubletHeatPlant")
    assert not fresh.is_initialized
    fresh.set_state_dict(example.state_dict())
    assert fresh.is_initialized


def test_the_treatment_design_is_complete_and_valid():
    """Every port is connected and every parameter has a value."""
    plant = treatment_plant()
    assert plant.is_initialized
    assert gm.plants.validate(plant, on_error="record") == []
    assert plant.d0.reservoir.temperature == plant.d1.reservoir.temperature
    assert plant.heat_users.fluid == gm.WATER


def test_names_lists_the_plants_of_a_purpose():
    """``category`` is what a plant serves; a building block serves nothing by itself."""
    assert catalogue.names("heating") == ["HeatingPlant"]
    assert "HeatingCoolingPlant" in catalogue.names("both")
    assert "Doublet" not in catalogue.names("both") + catalogue.names("heating")
    with raises(gm.errors.ValidationError, "unknown_name"):
        catalogue.names("steam")


def test_validate_gives_the_same_for_a_plant_and_its_dict():
    """A good plant and a broken one: the plant and its structure dict agree."""
    good = treatment_plant()
    assert gm.plants.validate(good, on_error="record") == gm.plants.validate(
        good.to_dict(structure=True), on_error="record"
    )
    broken = gm.Plant("Open")
    broken.add("Degasser", "degasser")
    found = gm.plants.validate(broken, on_error="record")
    assert found and found == gm.plants.validate(broken.to_dict(structure=True), on_error="record")
