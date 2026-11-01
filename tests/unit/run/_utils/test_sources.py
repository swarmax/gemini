"""The marginal cost of a source, from the prices of a problem."""

from pathlib import Path

import numpy as np
import pytest

import gemini as gm
from gemini.physics import refrigeration
from gemini.run._utils import sources
from tests.fixtures.errors import raises


def costs(steps=2, prices=None, **fields):
    """Return the prices of ``Assumptions`` with ``fields`` for ``steps`` rows, in SI."""
    per_joule = {
        name: gm.units.Quantity(price, "currency/J") for name, price in (prices or {}).items()
    }
    return sources.Costs(gm.Assumptions(prices=per_joule, **fields), steps)


def test_a_cost_is_the_price_over_the_efficiency():
    """One number per step, whatever the efficiency."""
    cost = costs(prices={"electricity": 3e-8}).electric("hp", 3.0)
    assert cost == pytest.approx([1e-8, 1e-8])


def test_a_price_profile_gives_a_cost_per_step():
    """A profile on the demand index reaches each step."""
    cost = costs(prices={"electricity": [1e-8, 3e-8]}).electric("hp", 1.0)
    assert cost.tolist() == pytest.approx([1e-8, 3e-8])


def test_the_carbon_price_adds_the_emission_of_the_carrier():
    """Gas burns to CO2; electricity emits what its factor says."""
    gas = costs(prices={"gas": 0.0}, co2_price=gm.units.Quantity(1.0, "currency/kg")).gas(
        "boiler", 1.0
    )
    assert gas[0] == pytest.approx(sources.dispatch.methane_emission_factor())
    power = costs(
        prices={"electricity": 0.0},
        co2_price=gm.units.Quantity(1.0, "currency/kg"),
        electricity_emission_factor=gm.units.Quantity(2e-8, "kg/J"),
    )
    assert power.electric("hp", 1.0)[0] == pytest.approx(2e-8)


def test_a_missing_price_names_the_carrier_and_the_source():
    """The price is a part of the problem: ``missing_value``."""
    with raises(gm.errors.ValidationError, "missing_value", match="boiler"):
        costs().gas("boiler", 0.9)


def _heat_pump(**params):
    """Return a heat pump with the values of ``params``."""
    return gm.modules.HeatPump().set_params(
        "", {"mode": "heating", "capacity": {"value": 1, "unit": "MW"}} | params
    )


def test_the_cop_of_the_estimate_follows_the_parameter_of_the_module():
    """No fraction is held in the dispatch: changing the parameter changes the COP."""
    low = sources.heat_pump_cop(_heat_pump(carnot_fraction=0.4), True, 373.15, 323.15)
    high = sources.heat_pump_cop(_heat_pump(carnot_fraction=0.6), True, 373.15, 323.15)
    assert high == pytest.approx(1.5 * low)


def test_a_lorenz_machine_is_estimated_with_its_own_fraction():
    """``lorenz_fraction`` counts for a Lorenz machine and ``carnot_fraction`` does not."""
    lorenz = {"cop_model": "lorenz", "lorenz_fraction": 0.3, "carnot_fraction": 0.6}
    plain = sources.heat_pump_cop(_heat_pump(carnot_fraction=0.3), True, 373.15, 323.15)
    assert sources.heat_pump_cop(_heat_pump(**lorenz), True, 373.15, 323.15) == plain


def test_the_default_fraction_is_a_named_value_with_a_source():
    """The default of the parameter is the named constant, and its docstring cites the source."""
    assert gm.modules.HeatPump().carnot_fraction == refrigeration.DEFAULT_CARNOT_FRACTION
    assert "ABB Review 5/1996" in Path(refrigeration.__file__).read_text()


def test_drive_heat_costs_the_cheapest_heat_over_the_cop():
    """Each step takes its cheapest source."""
    cheapest = [np.array([1.0, 4.0]), np.array([2.0, 2.0])]
    assert sources.drive_cost(cheapest, 2.0).tolist() == [0.5, 1.0]
