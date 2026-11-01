"""The levelised and the annualised cost with a plant that already has its design values."""

import pytest

from gemini.evaluate._utils import levelised
from gemini.units import Quantity
from tests.fixtures.cases import costed_finance, make_case
from tests.fixtures.costed_plants import day, heating_plant

CASE = make_case(finance=costed_finance(opex={"electricity": Quantity(2e-8, "currency/J")}))


def test_the_annualised_cost_is_the_levelised_cost_times_the_energy_over_the_share():
    """With the whole cost on the heat, ``lcoh`` times the heat is the annualised cost."""
    plant, run = heating_plant(), day()
    annual = levelised.annualised(plant, CASE, run, (0.05, 20), "raise")
    heat = levelised.levelised(plant, CASE, run, "heat", (0.05, 20), "raise")
    assert annual.value == pytest.approx(heat.value * heat.parts["energy"].value, rel=1e-12)


def test_a_missing_product_has_no_levelised_cost():
    """No cold is delivered."""
    found = levelised.levelised(heating_plant(), CASE, day(), "cold", (0.05, 20), "record")
    assert found.value is None and found.reason == "the run delivers no cold"
