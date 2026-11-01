"""Annual operating cost against the declared costs and hand sums."""

import pytest

import gemini as gm
from gemini.evaluate._utils import cost
from gemini.units import SECONDS_PER_YEAR
from tests.fixtures.costed_plants import HOURS, day, heating_plant
from tests.fixtures.result_tables import make_problem, make_results

HEAT_PER_YEAR = 1000.0 * SECONDS_PER_YEAR
"""Heat [J/year] of 1000 W delivered all year."""

GRID_PER_YEAR = 100.0 * SECONDS_PER_YEAR
"""Grid electricity [J/year] of 100 W drawn all year."""


def priced(**prices):
    """Return a problem whose assumptions hold ``prices``."""
    quantities = {name: gm.units.Quantity(price, "currency/J") for name, price in prices.items()}
    return make_problem(assumptions=gm.Assumptions(prices=quantities))


def test_opex_adds_fixed_variable_and_energy_bill():
    """10 EUR fixed, 1e-9 EUR/J of heat and the electricity at 2e-8 EUR/J."""
    result = gm.evaluate.opex(heating_plant(), priced(electricity=2e-8), day())
    components = {name: item.value for name, item in result.parts["components"].items()}
    assert {item.unit for item in result.parts["components"].values()} == {"currency/yr"}
    assert components["fixed"] == 10.0
    assert components["variable"] == pytest.approx(1e-9 * HEAT_PER_YEAR, rel=1e-12)
    assert components["electricity"] == pytest.approx(2e-8 * GRID_PER_YEAR, rel=1e-12)
    assert components["fuel"] == 0.0
    assert "co2" not in components
    assert result.value == pytest.approx(sum(components.values()), rel=1e-12)
    assert result.unit == "currency/yr"


def test_opex_needs_the_price_of_an_energy_the_run_draws():
    """Electricity is drawn but has no price: the user is asked, not guessed for."""
    with pytest.raises(gm.errors.ValidationError, match="electricity") as error:
        gm.evaluate.opex(heating_plant(), make_problem(), day())
    assert error.value.code == "missing_assumption"


def test_opex_without_declared_costs_reports_only_the_bill():
    """No declared cost: the value is null and says why; the bill is still given."""
    result = gm.evaluate.opex(
        heating_plant(costed=False), priced(electricity=2e-8), day(), on_error="record"
    )
    assert result.value is None and result.reason == cost.NO_COST
    assert result.parts["components"]["electricity"].value == pytest.approx(
        2e-8 * GRID_PER_YEAR, rel=1e-12
    )


def test_opex_refuses_prices_in_another_currency():
    """A cost in EUR and assumptions in USD do not mix."""
    values = gm.Assumptions(
        currency="USD", prices={"electricity": gm.units.Quantity(2e-8, "currency/J")}
    )
    with pytest.raises(gm.errors.ValidationError, match="currency"):
        gm.evaluate.opex(heating_plant(), make_problem(assumptions=values), day())


def test_a_price_profile_bills_the_hours_that_draw_power():
    """Power drawn only in the dear half of the day is billed at the dear price."""
    run = make_results({"grid": {"net_import": [0.0] * 12 + [100.0] * 12}})
    profile = priced(electricity=[1e-8] * 12 + [3e-8] * 12)
    result = gm.evaluate.opex(heating_plant(costed=False), profile, run, on_error="record")
    assert result.parts["components"]["electricity"].value == pytest.approx(
        3e-8 * 100.0 * SECONDS_PER_YEAR / 2
    )


def test_a_co2_price_adds_one_component_per_year():
    """1 kg/s of CO2 for a day, scaled to a year, at 0.5 EUR/kg."""
    run = make_results({"air": {"co2_emission": [1.0] * HOURS}})
    values = gm.Assumptions(co2_price=gm.units.Quantity(0.5, "currency/kg"))
    result = gm.evaluate.opex(
        heating_plant(costed=False), make_problem(assumptions=values), run, on_error="record"
    )
    assert result.parts["components"]["co2"].value == pytest.approx(0.5 * SECONDS_PER_YEAR)
    assert result.parts["components"]["co2"].unit == "currency/yr"
    without = gm.evaluate.opex(heating_plant(costed=False), make_problem(), run, on_error="record")
    assert "co2" not in without.parts["components"]
