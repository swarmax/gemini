"""Levelised cost of heat against the closed-form annuity."""

import pytest

import gemini as gm
from gemini._utils.jsonable import to_plain
from gemini.evaluate._utils import cost
from gemini.modules import CoolingGrid
from gemini.units import SECONDS_PER_YEAR, Quantity
from tests.fixtures.cases import costed_finance, make_case
from tests.fixtures.costed_plants import day, heating_plant
from tests.fixtures.errors import raises

PRICES = make_case(finance=costed_finance(opex={"electricity": Quantity(2e-8, "currency/J")}))
HEAT = 1000.0 * SECONDS_PER_YEAR
OPEX = 10.0 + 2e-8 * 100.0 * SECONDS_PER_YEAR
"""Yearly cost of the heating plant under ``PRICES``: the fixed opex and the electricity."""


def test_lcoh_is_discounted_cost_over_discounted_heat():
    """(capex + opex A) / (heat A) with the annuity factor of 5 % over 20 years."""
    factor = (1 - 1.05**-20) / 0.05
    result = gm.evaluate.lcoh(heating_plant(), PRICES, day(), 0.05, 20)
    assert result.value == pytest.approx((1000.0 + OPEX * factor) / (HEAT * factor), rel=1e-12)
    assert result.unit == "currency/J"
    assert to_plain(result.parts["capex"]) == {"value": 1000.0, "unit": "currency"}
    assert result.parts["opex"].value == pytest.approx(OPEX, rel=1e-12)


def test_lcoh_at_zero_rate_spreads_the_cost_over_the_years():
    """Without discounting, the cost over the lifetime divided by the heat over the lifetime."""
    result = gm.evaluate.lcoh(heating_plant(), PRICES, day(), 0.0, 10)
    assert result.value == pytest.approx((1000.0 + OPEX * 10) / (HEAT * 10), rel=1e-12)


def test_the_rate_and_lifetime_come_from_the_finance():
    """Given in the finance of the case, they give the same value as passed explicitly."""
    both = make_case(
        finance=costed_finance(
            opex={"electricity": Quantity(2e-8, "currency/J")},
            discount_rate=0.05,
            lifetime=Quantity(20, "yr"),
        )
    )
    explicit = gm.evaluate.lcoh(heating_plant(), PRICES, day(), 0.05, 20)
    assert gm.evaluate.lcoh(heating_plant(), both, day()) == explicit


def test_a_missing_rate_is_asked_for():
    """No rate anywhere raises with the missing-value code."""
    with raises(
        gm.errors.ValidationError,
        "missing_assumption",
        match=r"assumptions\.finance\.discount_rate",
    ):
        gm.evaluate.lcoh(heating_plant(), PRICES, day(), None, 20)


def test_null_with_a_reason_when_the_equipment_or_the_heat_is_missing():
    """No equipment, no heat delivered, or heat and cold together give no value."""
    unpriced = gm.evaluate.lcoh(
        heating_plant(costed=False), PRICES, day(), 0.05, 20, on_error="record"
    )
    assert unpriced.value is None and "no module of the plant is equipment" in unpriced.reason
    idle = gm.evaluate.lcoh(heating_plant(), PRICES, day(heat=0.0), 0.05, 20, on_error="record")
    assert idle.reason == "the run delivers no heat"
    plant = heating_plant()
    plant._add_module("cool", CoolingGrid())
    both = gm.evaluate.lcoh(plant, PRICES, day(cold=100.0), 0.05, 20, on_error="record")
    assert both.value is None and "split of its cost" in both.reason
    with raises(gm.errors.ValidationError, "no_value", match="split of its cost"):
        gm.evaluate.lcoh(plant, PRICES, day(cold=100.0), 0.05, 20)


def test_lcoh_keeps_its_numbers():
    """One expression, one order of operations: bit for bit the lifetime cost over the energy."""
    factor = cost.annuity(0.05, 20)
    result = gm.evaluate.lcoh(heating_plant(), PRICES, day(), 0.05, 20)
    capex, yearly, energy = (result.parts[name].value for name in ("capex", "opex", "energy"))
    assert result.value == (capex + yearly * factor) / (energy * factor)
