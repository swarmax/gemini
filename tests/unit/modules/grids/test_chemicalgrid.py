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
    result = plant(
        feed=gm.Stream(
            m_dot=gm.units.Quantity(50, "kg/s"),
            T=gm.units.Quantity(300, "K"),
            p=gm.units.Quantity(2e5, "Pa"),
        )
    )
    assert result.children["chemicals"].outlets.chemical_out.m_dot == 5e-4
    assert isinstance(plant.dosing, InhibitorDosing)


def test_traced_call_matches_one_call_per_row():
    """A grid without a taker traces."""
    assert_module_matches(ChemicalGrid(), [{}, {}])
