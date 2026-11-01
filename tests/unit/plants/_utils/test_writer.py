"""Writing a built plant: stated values stay as written while they are true."""

import gemini as gm
from gemini.modules._utils.serialization import tree_params
from tests.fixtures import si
from tests.fixtures.designs import with_values


def test_a_stated_unit_string_stays_while_the_value_is_unchanged():
    """The stated unit is kept; a changed value is a quantity in SI; unstated defaults stay out."""
    plant = gm.Plant("Units")
    plant.add("Pipe", "pipe", params={"length": {"value": 100, "unit": "ft"}})
    assert plant.to_dict()["modules"]["pipe"]["params"] == {"length": {"value": 100, "unit": "ft"}}
    si.set_params(plant, "pipe", {"length": 1500.0})
    assert plant.to_dict()["modules"]["pipe"]["params"] == {
        "length": {"value": 1500.0, "unit": "m"}
    }


def test_a_value_set_since_is_added():
    """A parameter nobody stated is written once it differs from its starting value."""
    plant = gm.Plant("Added")
    plant.add("Pipe", "pipe")
    assert plant.to_dict()["modules"]["pipe"] == {"type": "Pipe", "params": {}}
    si.set_params(plant, "pipe", {"inner_diameter": 0.3})
    assert plant.to_dict()["modules"]["pipe"]["params"] == {
        "inner_diameter": {"value": 0.3, "unit": "m"}
    }


def test_a_group_writes_its_children_and_a_plant_its_registered_name():
    """Groups nest ``modules``; a nested plant is written by name."""
    plant = gm.Plant("Groups")
    plant.add("ModuleDict", "filters")
    plant.add("Filter", "filters.hot")
    plant.add("Doublet", "doublet")
    modules = plant.to_dict()["modules"]
    assert modules["filters"] == {
        "type": "ModuleDict",
        "modules": {"hot": {"type": "Filter", "params": {}}},
    }
    assert modules["doublet"]["type"] == "Doublet"


def test_baseline_is_the_starting_values_of_the_tree():
    """A nested plant's baseline holds its dotted parameter names."""
    assert "reservoir.skin" in tree_params(with_values(gm.plants.get("Doublet")))
