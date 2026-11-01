"""Net present value against the closed form."""

import pytest

import gemini as gm
from gemini.units import SECONDS_PER_YEAR
from tests.fixtures.costed_plants import day, heating_plant
from tests.fixtures.errors import raises
from tests.fixtures.result_tables import make_problem

HEAT = 1000.0 * SECONDS_PER_YEAR
OPEX = 10.0 + 1e-9 * HEAT + 2e-8 * 100.0 * SECONDS_PER_YEAR
SELLING = make_problem(
    assumptions=gm.Assumptions(
        prices={
            "electricity": gm.units.Quantity(2e-8, "currency/J"),
            "heat": gm.units.Quantity(5e-8, "currency/J"),
        }
    )
)
NET = 5e-8 * HEAT - OPEX
"""Yearly net cash flow of the heating plant when its heat sells at 5e-8 EUR/J."""


def test_npv_is_the_discounted_net_cash_flow_less_the_investment():
    """-capex + net * A with A the 5 % annuity over 20 years."""
    factor = (1 - 1.05**-20) / 0.05
    result = gm.evaluate.npv(heating_plant(), SELLING, day(), 0.05, 20)
    assert result.value == pytest.approx(NET * factor - 1000.0, rel=1e-12)
    assert result.unit == "currency"
    assert result.parts["net_cash_flow"].value == pytest.approx(NET, rel=1e-12)
    assert result.parts["net_cash_flow"].unit == "currency/yr"


def test_a_missing_price_is_asked_for():
    """Heat is delivered but unpriced."""
    unpriced = make_problem(
        assumptions=gm.Assumptions(prices={"electricity": gm.units.Quantity(2e-8, "currency/J")})
    )
    with raises(gm.errors.ValidationError, "missing_assumption", match="heat"):
        gm.evaluate.npv(heating_plant(), unpriced, day(), 0.05, 20)


def test_a_plant_without_declared_cost_has_no_npv():
    """Null with the reason of the missing cost."""
    plant = heating_plant(costed=False)
    assert gm.evaluate.npv(plant, SELLING, day(), 0.05, 20, on_error="record").value is None
    with raises(gm.errors.ValidationError, "no_value", match="no module declares a cost"):
        gm.evaluate.npv(plant, SELLING, day(), 0.05, 20)


def test_a_heat_price_profile_is_integrated_over_the_run():
    """Half a day at 3e-8 and half at 7e-8 earns what a constant 5e-8 earns."""
    profile = make_problem(
        assumptions=gm.Assumptions(
            prices={
                "electricity": gm.units.Quantity(2e-8, "currency/J"),
                "heat": gm.units.Quantity([3e-8] * 12 + [7e-8] * 12, "currency/J"),
            }
        )
    )
    result = gm.evaluate.npv(heating_plant(), profile, day(), 0.05, 20)
    expected = gm.evaluate.npv(heating_plant(), SELLING, day(), 0.05, 20)
    assert result.value == pytest.approx(expected.value, rel=1e-12)
