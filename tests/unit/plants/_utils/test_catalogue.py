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
    "ATESPlant": "c701873fb9ab3804409b2cede107b27efda830d352bd2f2fe4d17af10da960e5",
    "BoilerChpPlant": "9f59d42f48d2608f95a4784ce4ecbbf68b8cf84c71f55f8749c76c8a77e41e7e",
    "CoolingSubstation": "3685c3ebc66824c6e0296386b373306ebe8254e9ad5d72b3cd2983fb7a2ba625",
    "DistrictEnergyPlant": "dc4fa5c020d5b7367d4c6d1c636998e7204e07fe77a240858a6f05955a27a3e0",
    "DistrictNetwork": "6f33b4f793e750d6efd7cc52934276a8a3ff2618ae5bd0b1c7c3106c90cdcab0",
    "Doublet": "edc05bcafb3e3e3fb4cc08aed776aeb1f2783ed0f914afe01d5d31e80dcf9d78",
    "DoubletHeatPlant": "30df8586e4eb31bf3b287b4f648f28c5091bfaa1b32580faaa197ea76a4540ed",
    "HeatingSubstation": "efb07bdf6b9e33ccad37d6fc0603938770d4142f3cb9dcacfcde1b12ae5ad48b",
    "MultiWellPlant": "ae8ad0475f83134e0201f7acf997090a522f3624f21b2f264304ee35eaf99e07",
    "NodalDoublet": "c9e66f2c96e83152a5cc44cbb6169dd2e7d55d0098077554553666e56299544f",
    "ParallelExchangerPlant": "bc36d7c313e147191ef5ac30a2480d34fca3da8d44cd9771b6ba20875ad0490f",
}
"""Hash of ``to_dict()`` of the plant built from each whole example file these values replaced.

The hashes were taken again when the plant dict lost the values of the case and wrote every value
with a unit as ``{"value", "unit"}``; the design values are those of the files.
They were taken again when the declarations of the modules lost their default design values: each
file now states, with the value it effectively used, what a declaration used to default (a
roughness, an arrangement, an alarm threshold); no value changed.

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
    expected = {
        name: value for name, value in shared["modules"]["doublet"]["params"].items() if "." in name
    }
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
