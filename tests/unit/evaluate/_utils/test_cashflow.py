"""The yearly cash flow shared by the net present value and the payback."""

import pytest

import gemini as gm
from gemini.evaluate._utils.cashflow import net_cash_flow
from gemini.units import SECONDS_PER_YEAR
from tests.fixtures.costed_plants import day, heating_plant
from tests.fixtures.result_tables import make_problem

PRICES = gm.Assumptions(
    prices={
        "electricity": gm.units.Quantity(2e-8, "currency/J"),
        "heat": gm.units.Quantity(5e-8, "currency/J"),
    }
)


def test_the_net_cash_flow_is_the_revenue_less_the_yearly_cost():
    """Heat sold at 5e-8 EUR/J against fixed, variable and electricity cost."""
    problem = make_problem(assumptions=PRICES)
    capex, flow, unit, reason = net_cash_flow(heating_plant(), problem, day(), "raise")
    heat = 1000.0 * SECONDS_PER_YEAR
    opex = 10.0 + 1e-9 * heat + 2e-8 * 100.0 * SECONDS_PER_YEAR
    assert (capex, unit, reason) == (1000.0, "currency", None)
    assert flow == pytest.approx(5e-8 * heat - opex, rel=1e-12)


def test_a_plant_without_a_cost_has_no_cash_flow():
    """The numbers are None and the reason says why."""
    problem = make_problem(assumptions=PRICES)
    capex, flow, _, reason = net_cash_flow(heating_plant(costed=False), problem, day(), "record")
    assert capex is None and flow is None and "no module declares a cost" in reason
