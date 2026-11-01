"""Levelised cost of thermal supply against the levelised cost of heat."""

import pytest

import gemini as gm
from gemini.modules import CoolingGrid
from gemini.units import SECONDS_PER_YEAR, Quantity
from tests.fixtures.cases import costed_finance, make_case
from tests.fixtures.costed_plants import day, heating_plant
from tests.fixtures.errors import raises

PRICES = make_case(finance=costed_finance(opex={"electricity": Quantity(2e-8, "currency/J")}))
HEAT = 1000.0 * SECONDS_PER_YEAR
OPEX = 10.0 + 2e-8 * 100.0 * SECONDS_PER_YEAR
"""Yearly cost of the heating plant under ``PRICES``: the fixed opex and the electricity."""


def both_products():
    """Return a heat plant that also has a cooling consumer."""
    plant = heating_plant()
    plant._add_module("cool", CoolingGrid())
    return plant


def test_lcts_is_the_cost_of_heat_and_cold_together():
    """``lcoh`` with the whole cost on the heat, spread over both products; no share needed."""
    plant, run = both_products(), day(cold=500.0)
    shared = make_case(
        finance=costed_finance(
            opex={"electricity": Quantity(2e-8, "currency/J")},
            allocation=gm.case.Allocation(heat_cost_share=1.0),
        )
    )
    lcoh = gm.evaluate.lcoh(plant, shared, run, 0.05, 20)
    result = gm.evaluate.lcts(plant, PRICES, run, 0.05, 20)
    heat, cold = result.parts["heat"].value, result.parts["cold"].value
    assert heat == pytest.approx(HEAT) and cold == pytest.approx(HEAT / 2)
    assert result.value == pytest.approx(
        lcoh.value * lcoh.parts["energy"].value / (heat + cold), rel=1e-12
    )
    assert (
        result.unit == "currency/J"
        and result.parts["heat"].unit == result.parts["cold"].unit == "J/yr"
    )
    assert result.parts["annualised_cost"].unit == "currency/yr"


def test_lcts_of_one_product_is_its_levelised_cost():
    """A plant that delivers only heat has the same cost per joule both ways."""
    expected = gm.evaluate.lcoh(heating_plant(), PRICES, day(), 0.05, 20).value
    result = gm.evaluate.lcts(heating_plant(), PRICES, day(), 0.05, 20)
    assert result.value == pytest.approx(expected, rel=1e-12)
    assert result.parts["cold"].value == 0


def test_lcts_without_energy_has_no_value():
    """No heat and no cold: a reason, as ``lcoh`` gives; raised by default."""
    idle = day(heat=0.0)
    recorded = gm.evaluate.lcts(heating_plant(), PRICES, idle, 0.05, 20, on_error="record")
    assert recorded.value is None and "neither heat nor cold" in recorded.reason
    assert recorded.unit == "currency/J"
    with raises(gm.errors.ValidationError, "no_value", match="neither heat nor cold"):
        gm.evaluate.lcts(heating_plant(), PRICES, idle, 0.05, 20)


def test_a_result_converts_to_the_eur_units_of_a_report():
    """An LCTS is in ``EUR/MWh`` and a capex in ``EUR`` with ``.to``, whatever the label."""
    lcts = gm.evaluate.lcts(heating_plant(), PRICES, day(), 0.05, 20)
    assert lcts.to("EUR/MWh").value == pytest.approx(lcts.value * 3.6e9)
    capex = gm.evaluate.capex(heating_plant(), PRICES)
    assert capex.to("EUR").value == capex.value == 1000.0
    assert capex.to("MEUR").value == pytest.approx(1e-3)
