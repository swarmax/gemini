"""The flows at the edge of a plant, scaled to a year and priced."""

import numpy as np
import pytest

import gemini as gm
from gemini.evaluate._utils.flows import Flows
from gemini.units import SECONDS_PER_YEAR
from tests.fixtures.costed_plants import HOURS, cooling_plant, day, heating_plant
from tests.fixtures.errors import raises
from tests.fixtures.result_tables import make_problem, make_results

HEAT_PER_YEAR = 1000.0 * SECONDS_PER_YEAR
"""Heat [J/year] of 1000 W delivered all year."""

GRID_PER_YEAR = 100.0 * SECONDS_PER_YEAR
"""Grid electricity [J/year] of 100 W drawn all year."""


def test_energies_scale_the_window_to_a_year():
    """A day of 1000 W of heat is 1000 W for a year; 100 W of electricity is all grid."""
    flows = Flows(heating_plant(), day())
    assert flows.energy("heat") == pytest.approx(HEAT_PER_YEAR, rel=1e-12)
    assert flows.energy("electricity") == pytest.approx(GRID_PER_YEAR, rel=1e-12)
    assert flows.energy("cold") == 0.0 and flows.energy("fuel") == 0.0


def test_cold_is_counted_from_the_cooling_consumers():
    """Cold delivered per year comes from the cooling consumers."""
    flows = Flows(cooling_plant(), day(heat=None, cold=300.0))
    assert flows.energy("cold") == pytest.approx(300.0 * SECONDS_PER_YEAR, rel=1e-12)
    assert flows.energy("heat") == 0.0


def test_the_gas_price_buys_purchased_gas_only():
    """Co-produced gas costs nothing; a price per MWh prices what was purchased."""
    columns = {
        "grid": {"net_import": [0.0] * HOURS},
        "gas": {"gas_out.chemical_flow": [1e6] * HOURS},
    }
    flows = Flows(heating_plant(), make_results(columns))
    problem = make_problem(
        assumptions=gm.Assumptions(prices={"gas": {"value": 40.0, "unit": "EUR/MWh"}})
    )
    assert flows.energy("fuel") == pytest.approx(1e6 * SECONDS_PER_YEAR)
    assert flows.cost("fuel", problem) == pytest.approx(flows.energy("fuel") / 3.6e9 * 40.0)
    assert flows.cost("electricity", make_problem()) == 0.0
    with raises(gm.errors.ValidationError, "missing_assumption", match="gas"):
        flows.cost("fuel", make_problem())


def test_a_constant_price_multiplies_the_energy_of_the_year():
    """Bit for bit the energy of the year times the price."""
    flows = Flows(heating_plant(), day())
    problem = make_problem(
        assumptions=gm.Assumptions(prices={"electricity": gm.units.Quantity(2e-8, "currency/J")})
    )
    assert flows.cost("electricity", problem) == flows.energy("electricity") * 2e-8


def test_a_price_profile_is_integrated_over_the_run():
    """The power of each step times its price: half a day at 1 and half at 3 averages to 2."""
    flows = Flows(heating_plant(), day())
    price = [1e-8] * (HOURS // 2) + [3e-8] * (HOURS // 2)
    problem = make_problem(
        assumptions=gm.Assumptions(prices={"electricity": gm.units.Quantity(price, "currency/J")})
    )
    constant = make_problem(
        assumptions=gm.Assumptions(prices={"electricity": gm.units.Quantity(2e-8, "currency/J")})
    )
    assert flows.cost("electricity", problem) == pytest.approx(flows.cost("electricity", constant))


def test_a_profile_weights_the_hours_that_draw_power():
    """Power drawn only in the dear hours is billed at the dear price, not the mean."""
    power = [0.0] * (HOURS // 2) + [100.0] * (HOURS // 2)
    run = make_results({"grid": {"net_import": power}})
    price = np.array([1e-8] * (HOURS // 2) + [3e-8] * (HOURS // 2))
    problem = make_problem(
        assumptions=gm.Assumptions(
            prices={"electricity": gm.units.Quantity(list(price), "currency/J")}
        )
    )
    bill = Flows(heating_plant(), run).cost("electricity", problem)
    assert bill == pytest.approx(3e-8 * 100.0 * SECONDS_PER_YEAR / 2)


def test_a_profile_of_another_length_than_the_run_is_refused():
    """One price per step of the run."""
    problem = make_problem(
        count=4,
        assumptions=gm.Assumptions(
            prices={"electricity": gm.units.Quantity([1e-8] * 4, "currency/J")}
        ),
    )
    with raises(gm.errors.ValidationError, "invalid_value", match="one per step"):
        Flows(heating_plant(), day()).cost("electricity", problem)
