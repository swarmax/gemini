"""The plant catalogue: names and new plants."""

import hashlib
import json

import pytest

import gemini as gm
from gemini._utils import paths, registry
from gemini.plants._utils import catalogue
from tests.fixtures.errors import raises
from tests.fixtures.sample_cases import treatment_plant

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
    "BoilerChpPlant": "da243ef90c1b96fee03ac96a5d17fed5a5b5df8e3d5cf8528152d9ef5651d71a",
    "CoolingSubstation": "64e2a52f01d79151750d6c90bd03b77ee1fef3e0f18111931cb8dd0cc025e24b",
    "DistrictEnergyPlant": "ebce116425f8cb0bbbb10439e56a05def20c6bb3a9130daf005045042af64095",
    "DistrictNetwork": "d9c9f286535f517fc5b575bd33d2861a5dcf45f65e1d2181c186d412b0c5ed94",
    "Doublet": "55c5c24d9459060e48c1dac9b0398e0b2e27adf635223995cedf7d73cfee4ad4",
    "DoubletHeatPlant": "208e5c874eb6d44b5c75f80f1872c59767451facdcce17bfe65a278aa2fea6e9",
    "HeatingSubstation": "4f28ac09ac50639d8f0d3be2dfaf53650cb414105622b4401c27ccbe143eb73c",
    "MultiWellPlant": "23e77a37e0438cace214f60ccf545ac0da9954cf9a42b10fe5aaaa907c0ea3f1",
    "NodalDoublet": "0f4e678cf8d887edaa8b053d60ccfdf30571eaf726904ff7d9f3851c7b23f9d1",
    "ParallelExchangerPlant": "77034434e00aa6d8f7d9ac0af523343c1662b0a5348dc549280ed99da84494ca",
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
    spec = catalogue.example(name).to_dict()
    assert gm.plants.validate(spec) == []
    assert gm.Plant.from_dict(spec).to_dict() == spec


@pytest.mark.parametrize("name", EXAMPLES)
def test_every_example_equals_the_plant_of_its_former_file(name):
    """``get`` and the values of ``inputs/plants/`` give the structure and the values pinned."""
    spec = catalogue.example(name).to_dict(structure=True)
    if name == "Doublet":
        del spec["outputs"]
    text = json.dumps(spec, sort_keys=True)
    assert hashlib.sha256(text.encode()).hexdigest() == FORMER_EXAMPLES[name]


def test_the_doublet_examples_carry_the_shared_doublet_heat_values():
    """The doublet is the ``doublet`` child of the doublet heat plant."""
    shared = catalogue.example("DoubletHeatPlant").to_dict(structure=True)
    doublet = catalogue.example("Doublet")
    expected = shared["modules"]["doublet"]["params"]
    assert {
        f"{path}.{name}": value
        for path, entry in doublet.to_dict(structure=True)["modules"].items()
        for name, value in entry["params"].items()
    } == expected


def test_the_other_examples_carry_the_values_of_their_tests(plants):
    """The substations and the network are filled as the unit tests of their folder fill them."""
    heating = plants["heating_substation"](catalogue.get("HeatingSubstation"))
    assert catalogue.example("HeatingSubstation").state_dict() == heating.state_dict()
    cooling = plants["cooling_substation"](catalogue.get("CoolingSubstation"))
    assert catalogue.example("CoolingSubstation").state_dict() == cooling.state_dict()
    network = plants["network"](catalogue.get("DistrictNetwork"), plants["heating_substation"])
    assert catalogue.example("DistrictNetwork").state_dict() == network.state_dict()


def test_a_state_dictionary_fills_a_plant_without_values():
    """A plant from ``get`` has no values and takes those of an example; groups stay groups."""
    example = catalogue.example("DoubletHeatPlant")
    assert isinstance(example.filters, gm.modules.ModuleDict)
    fresh = catalogue.get("DoubletHeatPlant")
    assert not fresh.is_initialized
    fresh.set_state_dict(example.state_dict())
    assert fresh.is_initialized


@pytest.mark.parametrize("name", TEMPLATE_PLANTS)
def test_a_template_plant_has_no_example(name):
    """Its values belong to a problem, so ``example`` says so and ``get`` still gives the plant."""
    with pytest.raises(gm.errors.NotImplementedYet, match=name):
        catalogue.example(name)
    assert not catalogue.get(name).is_initialized


def test_the_treatment_design_is_complete_and_valid():
    """Every port is connected and every parameter has a value."""
    plant = treatment_plant()
    assert plant.is_initialized
    assert plant.validate(on_error="record") == []
    assert plant.d0.reservoir.temperature == plant.d1.reservoir.temperature
    assert plant.heat_users.fluid == gm.WATER


def test_a_registered_plant_without_values_names_itself(monkeypatch):
    """Only a plant with no sourced values raises, and the message names it."""
    entry = registry._Entry("plants", module=type("Unsourced", (gm.Plant,), {}))
    monkeypatch.setitem(registry._entries, "Unsourced", entry)
    with pytest.raises(gm.errors.NotImplementedYet, match="Unsourced"):
        catalogue.example("Unsourced")


def test_an_example_needs_a_source_checkout(tmp_path, monkeypatch):
    """Without ``inputs/`` the error names the file; the plant itself stays available."""
    monkeypatch.setattr(paths, "INPUTS", tmp_path / "absent")
    with raises(gm.errors.RunError, "inputs_missing") as missing:
        catalogue.example("Doublet")
    assert "plants/Doublet.json" in str(missing.value)
    assert catalogue.get("Doublet").name == "Doublet"


def test_example_refuses_unknown_names_with_close_matches():
    """A misspelt plant name has suggestions."""
    with raises(gm.errors.ValidationError, "unknown_name") as unknown:
        catalogue.example("Doublt")
    assert "Doublet" in unknown.value.suggestions


def test_names_lists_the_plants_of_a_purpose():
    """``category`` is what a plant serves; a building block serves nothing by itself."""
    assert catalogue.names("heating") == ["HeatingPlant"]
    assert "HeatingCoolingPlant" in catalogue.names("both")
    assert "Doublet" not in catalogue.names("both") + catalogue.names("heating")
    with raises(gm.errors.ValidationError, "unknown_name"):
        catalogue.names("steam")
