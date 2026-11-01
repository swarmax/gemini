"""Simple payback against the closed form."""

import pytest

import gemini as gm
from gemini.units import SECONDS_PER_YEAR, Quantity
from tests.fixtures.cases import costed_finance, make_case
from tests.fixtures.costed_plants import day, heating_plant
from tests.fixtures.errors import raises

HEAT = 1000.0 * SECONDS_PER_YEAR
OPEX = 10.0 + 2e-8 * 100.0 * SECONDS_PER_YEAR
SELLING = make_case(
    finance=costed_finance(
        opex={"electricity": Quantity(2e-8, "currency/J")},
        revenue={"heat": Quantity(5e-8, "currency/J")},
    )
)
NET = 5e-8 * HEAT - OPEX
"""Yearly net cash flow of the heating plant when its heat sells at 5e-8 EUR/J."""


def test_payback_is_the_investment_over_the_net_cash_flow():
    """Simple payback in years, undiscounted."""
    result = gm.evaluate.payback(heating_plant(), SELLING, day())
    assert result.value == pytest.approx(1000.0 / NET, rel=1e-12)
    assert result.unit == "yr"


def test_payback_never_comes_when_revenue_does_not_cover_the_cost():
    """A heat price below the running cost gives null with the reason."""
    cheap = make_case(
        finance=costed_finance(
            opex={"electricity": Quantity(2e-8, "currency/J")},
            revenue={"heat": Quantity(1e-9, "currency/J")},
        )
    )
    result = gm.evaluate.payback(heating_plant(), cheap, day(), on_error="record")
    assert result.value is None
    assert result.reason == "the yearly revenue does not exceed the yearly cost"


def test_the_price_of_heat_is_asked_for_when_heat_is_delivered():
    """Heat is delivered but unpriced: the user is asked."""
    unpriced = make_case(finance=costed_finance(opex={"electricity": Quantity(2e-8, "currency/J")}))
    with raises(
        gm.errors.ValidationError,
        "missing_assumption",
        match=r"assumptions\.finance\.revenue\.heat",
    ):
        gm.evaluate.payback(heating_plant(), unpriced, day())


def test_a_plant_without_equipment_has_no_payback():
    """Null with the reason of the missing cost."""
    plant = heating_plant(costed=False)
    recorded = gm.evaluate.payback(plant, SELLING, day(), on_error="record")
    assert "no module of the plant is equipment" in recorded.reason
    with raises(gm.errors.ValidationError, "no_value", match="no module of the plant is equipment"):
        gm.evaluate.payback(plant, SELLING, day())
