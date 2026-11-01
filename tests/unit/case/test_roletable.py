"""``gm.case.roles()`` and the units of a role in a plant, found by class."""

import gemini as gm
from gemini.case import roletable as roles_module
from gemini.plants._utils.roles import units_of
from tests.fixtures.errors import raises


def test_the_table_lists_every_role_with_its_quantities():
    """The closed table of the task, as a copy."""
    table = gm.case.roles()
    assert list(table) == [
        "doublet",
        "heat_pump",
        "boiler",
        "chp",
        "chiller",
        "heat_exchanger",
        "heating_supply",
        "cooling_supply",
        "plant",
    ]
    assert table["doublet"][:2] == ["production_flow", "brine_cooling"]
    table["doublet"].clear()
    assert gm.case.roles()["doublet"]


def test_reading_a_quantity_the_role_lacks_lists_the_role_quantities():
    """``cop`` is not a quantity of a doublet."""
    with raises(gm.errors.ValidationError, "invalid_value") as caught:
        roles_module.reads("doublet", "cop")
    assert "production_flow" in str(caught.value)


def test_units_are_found_by_class_whatever_their_name():
    """A plant of a class holds its doublets, boiler and consumer under any name."""
    plant = gm.plants.HeatingPlant()
    assert units_of(plant, "doublet") == ["d0"]
    assert units_of(plant, "boiler") == ["peak_boiler"]
    assert units_of(plant, "heating_supply") == ["heating_consumer"]
    assert units_of(plant, "chiller") == []


def test_a_heat_pump_is_a_chiller_when_it_feeds_the_cooling_grid():
    """The same class is a heat pump or a compression chiller, by the grid it reaches."""
    plant = gm.plants.HeatingHeatPumpCoolingPlant()
    assert units_of(plant, "heat_pump") == ["heat_pump"]
    assert units_of(plant, "chiller") == ["compression_chiller"]


def test_doublets_are_found_under_any_name():
    """A plant built by hand names its doublets as it likes."""
    plant = gm.Plant("site")
    plant.add(gm.plants.Doublet, "north")
    plant.add(gm.plants.Doublet, "south")
    assert units_of(plant, "doublet") == ["north", "south"]
