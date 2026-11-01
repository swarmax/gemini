"""The levelised and the annualised cost with a plant that already has its site."""

import pytest

import gemini as gm
from gemini.evaluate._utils import levelised
from tests.fixtures.costed_plants import day, heating_plant
from tests.fixtures.result_tables import make_problem

PROBLEM = make_problem(
    assumptions=gm.Assumptions(prices={"electricity": gm.units.Quantity(2e-8, "currency/J")})
)


def test_the_annualised_cost_is_the_levelised_cost_times_the_energy_over_the_share():
    """With the whole cost on the heat, ``lcoh`` times the heat is the annualised cost."""
    plant, run = heating_plant(), day()
    annual = levelised.annualised(plant, PROBLEM, run, (0.05, 20), "raise")
    heat = levelised.levelised(plant, PROBLEM, run, "heat", (0.05, 20), "raise")
    assert annual.value == pytest.approx(heat.value * heat.parts["energy"].value, rel=1e-12)


def test_a_missing_product_has_no_levelised_cost():
    """No cold is delivered."""
    found = levelised.levelised(heating_plant(), PROBLEM, day(), "cold", (0.05, 20), "record")
    assert found.value is None and found.reason == "the run delivers no cold"
