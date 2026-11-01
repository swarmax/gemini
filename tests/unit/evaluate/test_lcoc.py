"""Levelised cost of cold against the closed-form annuity."""

import pytest

import gemini as gm
from gemini.modules import CoolingGrid
from gemini.units import SECONDS_PER_YEAR, Quantity
from tests.fixtures.cases import costed_finance, make_case
from tests.fixtures.costed_plants import cooling_plant, day, heating_plant

PRICES = make_case(finance=costed_finance(opex={"electricity": Quantity(2e-8, "currency/J")}))
HEAT = 1000.0 * SECONDS_PER_YEAR
OPEX = 10.0 + 2e-8 * 100.0 * SECONDS_PER_YEAR
"""Yearly cost of the heating plant under ``PRICES``: the fixed opex and the electricity."""


def test_a_share_splits_the_cost_of_a_plant_with_two_products():
    """``heat_cost_share`` charges that part of the cost to heat and the rest to cold."""
    plant = heating_plant()
    plant._add_module("cool", CoolingGrid())
    run = day(cold=100.0)
    values = make_case(
        finance=costed_finance(
            opex={"electricity": Quantity(2e-8, "currency/J")},
            allocation=gm.case.Allocation(heat_cost_share=0.8),
        )
    )
    heat = gm.evaluate.lcoh(plant, values, run, 0.05, 20)
    cold = gm.evaluate.lcoc(plant, values, run, 0.05, 20)
    assert heat.value * heat.parts["energy"].value / 0.8 == pytest.approx(
        cold.value * cold.parts["energy"].value / 0.2
    )


def test_lcoc_divides_by_the_cold_delivered():
    """The cooling plant (2000, fixed opex 60 a year, 300 W of cold) over 10 years at 0 %."""
    values = PRICES
    result = gm.evaluate.lcoc(cooling_plant(), values, day(heat=None, cold=300.0), 0.0, 10)
    opex = 60.0 + 2e-8 * 100.0 * SECONDS_PER_YEAR
    expected = (2000.0 + opex * 10) / (300.0 * SECONDS_PER_YEAR * 10)
    assert result.value == pytest.approx(expected, rel=1e-12)
