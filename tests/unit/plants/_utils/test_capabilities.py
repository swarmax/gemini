"""``gm.plants.capabilities``: what each plant class contains, plans and lets a study choose."""

import pytest

import gemini as gm


@pytest.fixture(scope="module")
def found():
    """Return the capabilities of every plant class."""
    return gm.plants.capabilities()


def test_every_plant_class_is_listed(found):
    """The keys are the registered plant classes."""
    assert list(found) == gm.plants.names()


def test_the_roles_are_roles_of_the_case(found):
    """Every role is a key of ``gm.case.roles()``,."""
    assert all(set(item["roles"]) <= set(gm.case.roles()) for item in found.values())


def test_a_heating_cooling_plant_has_what_it_is_made_of(found):
    """The roles by class and wiring."""
    roles = set(found["HeatingHeatPumpCoolingPlant"]["roles"])
    assert roles >= {
        "doublet",
        "heat_pump",
        "boiler",
        "chiller",
        "heating_supply",
        "cooling_supply",
    }
    assert "heat_pump" not in found["HeatingFullCoolingPlant"]["roles"]


def test_the_schedule_plans_plants_with_doublets_and_a_grid(found):
    """A substation has no doublet, a doublet alone is no child: not planned."""
    planned = {name for name, item in found.items() if item["schedulable"]}
    assert (
        "DoubletHeatPlant" in planned
        and "HeatingPlant" in planned
        and "HeatingCoolingPlant" in planned
    )
    assert not planned & {"ATESPlant", "HeatingSubstation", "Doublet"}


def test_the_choices_follow_the_class(found):
    """Doublets need the structural size, depth a depth parameter."""
    assert found["HeatingPlant"]["choices"] == ["doublets", "depth"]
    assert found["Doublet"]["choices"] == ["depth"]
    assert found["HeatingSubstation"]["choices"] == []
