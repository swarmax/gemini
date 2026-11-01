"""Variables named after a role: the names they stand for and their quantities."""

import gemini as gm
from gemini.study._utils.roles import concrete, expanded, quantities
from tests.fixtures.sample_cases import HACKATHON_2026
from tests.unit.study.conftest import shallow_case, shallow_plant


def hackathon_plant():
    """Return the stored plant whose doublets each have a depth and which has none of its own."""
    return gm.Plant.from_json(HACKATHON_2026 / "plants/HackathonPlant.json")


def test_a_role_variable_stands_for_the_parameter_of_each_unit_of_the_role():
    """``<role>.<parameter>`` names every unit; a role the plant lacks gives none."""
    plant = hackathon_plant()
    assert concrete(plant, "doublet.depth") == ["d0.depth", "d1.depth"]
    assert concrete(shallow_plant(), "chiller.capacity") == ["compression_chiller.capacity"]
    assert concrete(shallow_plant(), "chp.capacity") == []


def test_depth_without_a_depth_of_the_plant_is_the_depth_of_each_doublet():
    """A plant with its own depth keeps the name; one without spreads it over the doublets."""
    assert concrete(hackathon_plant(), "depth") == ["d0.depth", "d1.depth"]
    assert concrete(shallow_plant(), "depth") == ["depth"]


def test_any_other_name_stands_for_itself():
    """A path, a case path and the doublet count are not roles."""
    plant = shallow_plant()
    for name in (
        "size.doublets",
        "case.assumptions.finance.opex.electricity",
        "peak_boiler.capacity",
    ):
        assert concrete(plant, name) == [name]


def test_the_values_are_given_to_every_concrete_name():
    """One number of a variable goes to each name it stands for; a lacking role drops out."""
    values = {"doublet.depth": 2500.0, "size.doublets": 2.0, "chp.capacity": 1.0}
    assert expanded(hackathon_plant(), values) == {
        "d0.depth": 2500.0,
        "d1.depth": 2500.0,
        "size.doublets": 2.0,
    }


def test_the_quantities_carry_the_si_unit_of_the_first_name():
    """Each value is a quantity in the unit of its parameter."""
    got = quantities(hackathon_plant(), shallow_case(), {"doublet.depth": 2500.0})
    assert got == {"doublet.depth": gm.units.Quantity(2500.0, "m")}
