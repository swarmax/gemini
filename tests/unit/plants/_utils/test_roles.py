"""The roles of a module, found from its class and its wiring."""

import gemini as gm
from gemini.plants._utils.roles import ROLES, roles_of, units_of


def test_the_roles_are_those_of_the_case_table():
    """One list of roles for the plants and the case."""
    assert set(ROLES) == set(gm.case.roles())


def test_a_machine_takes_its_role_from_the_grid_it_reaches():
    """The heat pump heats, the compression chiller cools."""
    plant = gm.plants.get("HeatingHeatPumpCoolingPlant")
    assert units_of(plant, "heat_pump") == ["heat_pump"]
    assert units_of(plant, "chiller") == ["compression_chiller"]
    module = plant.get_submodule("heat_pump")
    assert roles_of(plant, "heat_pump", module) == ["heat_pump"]


def test_a_plant_without_a_role_has_no_unit_of_it():
    """Nothing to find."""
    assert units_of(gm.plants.get("HeatingPlant"), "chiller") == []
