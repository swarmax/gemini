"""The plant's edge for bought chemicals."""

import gemini as gm
from gemini.modules import ChemicalGrid, InhibitorDosing
from tests.fixtures.equivalence import assert_module_matches

OFFER = ChemicalGrid()._offered()["chemical_out"]


def test_the_grid_offers_the_product_without_flow():
    """The dosing decides how much it takes."""
    assert OFFER.m_dot == 0


def test_the_dosed_amount_is_read_from_the_port():
    """A plant passes what the dosing drew back to the grid."""
    plant = gm.Plant("Dosed")
    plant.add("ChemicalGrid", "chemicals")
    plant.add("InhibitorDosing", "dosing", {"product_concentration": 0.4})
    plant.connect("chemicals.chemical_out", "dosing.chemical_in")
    plant.connect("feed", "dosing.fluid_in")
    plant.connect("dosing.fluid_out", "product")
    plant.dosing.dose = {"value": 10, "unit": "ppm"}
    result = plant(feed=gm.Stream(m_dot=50, T=300, p=2e5))
    assert result.children["chemicals"].outlets.chemical_out.m_dot == 5e-4
    assert isinstance(plant.dosing, InhibitorDosing)


def test_traced_call_matches_one_call_per_row():
    """A grid without a taker traces."""
    assert_module_matches(ChemicalGrid(), [{}, {}])
