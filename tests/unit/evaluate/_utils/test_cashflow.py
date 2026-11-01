"""The yearly cash flow shared by the net present value and the payback."""

import pytest

from gemini.evaluate._utils.cashflow import net_cash_flow
from gemini.units import SECONDS_PER_YEAR, Quantity
from tests.fixtures.cases import costed_finance, make_case
from tests.fixtures.costed_plants import day, heating_plant

CASE = make_case(
    finance=costed_finance(
        opex={"electricity": Quantity(2e-8, "currency/J")},
        revenue={"heat": Quantity(5e-8, "currency/J")},
    )
)


def test_the_net_cash_flow_is_the_revenue_less_the_yearly_cost():
    """Heat sold at 5e-8 per joule against the fixed opex and the electricity."""
    capex, flow, unit, reason = net_cash_flow(heating_plant(), CASE, day(), "raise")
    heat = 1000.0 * SECONDS_PER_YEAR
    opex = 10.0 + 2e-8 * 100.0 * SECONDS_PER_YEAR
    assert (capex, unit, reason) == (1000.0, "currency", None)
    assert flow == pytest.approx(5e-8 * heat - opex, rel=1e-12)


def test_a_plant_without_equipment_has_no_cash_flow():
    """The numbers are None and the reason says why."""
    capex, flow, _, reason = net_cash_flow(heating_plant(costed=False), CASE, day(), "record")
    assert capex is None and flow is None and "no module of the plant is equipment" in reason
