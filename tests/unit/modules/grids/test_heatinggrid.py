"""Heat delivery, return-temperature floor, zero flow and balances of the heat consumer."""

import pytest

import gemini as gm
from gemini.errors import PhysicsError, ValidationError
from gemini.modules import HeatingGrid, energy_balance, mass_balance
from gemini.types import Stream
from tests.fixtures import si
from tests.fixtures.equivalence import assert_module_matches
from tests.fixtures.errors import raises
from tests.fixtures.reading import reading

CP = 4217.4
SUPPLY = Stream(
    m_dot=gm.units.Quantity(2.0, "kg/s"),
    T=gm.units.Quantity(343.15, "K"),
    p=gm.units.Quantity(3e5, "Pa"),
)


def _consumer():
    return HeatingGrid().set_params("", {"minimum_return_temperature": {"value": 40, "unit": "C"}})


def test_met_demand_sets_the_return_temperature():
    """A demand below the available heat is met and cools the stream by Q / (m_dot cp)."""
    consumer = _consumer()
    result = consumer(supply_in=SUPPLY, heat_demand={"value": 100, "unit": "kW"})
    out, return_out = reading(result), result.outlets.return_out
    assert out.heat_supplied == pytest.approx(100e3)
    assert out.unmet_demand == 0 and not out.is_unmet
    assert out.return_out_T == pytest.approx(343.15 - 100e3 / (2 * CP))
    assert out.temperature_difference == pytest.approx(100e3 / (2 * CP))
    assert return_out.m_dot == SUPPLY.m_dot and return_out.p == SUPPLY.p
    assert return_out.T == out.return_out_T
    assert energy_balance(consumer, result)["relative_residual"] < 1e-12
    assert mass_balance(consumer, result)["residual"] == 0


def test_return_floor_caps_the_delivered_heat():
    """Demand beyond m_dot cp (T_supply - T_min) is unmet and the return sits at the floor."""
    consumer = _consumer()
    result = consumer(supply_in=SUPPLY, heat_demand=1e6)
    out = reading(result)
    assert out.heat_supplied == pytest.approx(2 * CP * 30)
    assert out.unmet_demand == pytest.approx(1e6 - 2 * CP * 30) and out.is_unmet
    assert out.return_out_T == 313.15 and out.temperature_difference == pytest.approx(30)
    assert energy_balance(consumer, result)["relative_residual"] < 1e-12


def test_zero_flow_cold_supply_and_zero_demand_deliver_nothing():
    """No flow, a supply below the floor or no demand leave the stream unchanged."""
    consumer = _consumer()
    for supply, demand in [(SUPPLY.with_(m_dot=0), 5e4), (SUPPLY.with_(T=303.15), 5e4)]:
        result = consumer(supply_in=supply, heat_demand=demand)
        assert reading(result).heat_supplied == 0 and result.outputs.unmet_demand == demand
        assert result.outputs.is_unmet and result.outlets.return_out.T == supply.T
        assert energy_balance(consumer, result)["relative_residual"] < 1e-12
    out = reading(consumer(supply_in=SUPPLY, heat_demand=0))
    assert out.heat_supplied == 0 and not out.is_unmet and out.temperature_difference == 0


def test_invalid_inputs_raise():
    """Reverse flow, negative demand and a missing demand or floor are rejected."""
    consumer = _consumer()
    with pytest.raises(PhysicsError, match="supply_in.m_dot = -1"):
        consumer(supply_in=SUPPLY.with_(m_dot=-1), heat_demand=1e4)
    with pytest.raises(ValidationError):
        consumer(supply_in=SUPPLY, heat_demand=-1)
    with raises(ValidationError, "missing_value"):
        consumer(supply_in=SUPPLY)
    with raises(ValidationError, "missing_value"):
        HeatingGrid()(supply_in=SUPPLY, heat_demand=1e4)


def test_traced_call_matches_one_call_per_row():
    """Met, short, cold-supply, no-demand and stopped rows trace and equal per-row calls."""
    rows = [
        dict(
            supply_in=Stream(
                m_dot=gm.units.Quantity(m_dot, "kg/s"),
                T=gm.units.Quantity(T, "K"),
                p=gm.units.Quantity(3e5, "Pa"),
            ),
            heat_demand=demand,
        )
        for m_dot, T, demand in [
            (2.0, 343.15, 100e3),
            (2.0, 343.15, 1e6),
            (2.0, 300.0, 100e3),
            (2.0, 343.15, 0.0),
            (0.0, 343.15, 100e3),
        ]
    ]
    assert_module_matches(_consumer(), rows)


CLOSED = {"return_temperature": 333.15, "return_pressure": 5e5}


def closed_loop():
    """Return a heat user on a closed loop: the return is fixed, the water brings what it brings."""
    grid = si.set_params(HeatingGrid(), "", CLOSED)
    grid.fluid = gm.WATER
    return grid


def rate(grid, heat, difference):
    """Return the flow [kg/s] that gives ``heat`` over a temperature ``difference``."""
    return heat / (grid.fluid.properties(0, 0).cp_l * difference)


def test_surplus_is_zero_when_the_supply_equals_the_demand():
    """Water that brings the demand leaves neither unmet heat nor a surplus."""
    grid = closed_loop()
    flow = rate(grid, 1e6, 40.0)
    supply = gm.Stream(
        m_dot=gm.units.Quantity(flow, "kg/s"),
        T=gm.units.Quantity(373.15, "K"),
        p=gm.units.Quantity(6e5, "Pa"),
        fluid=gm.WATER,
    )
    outputs = grid(supply_in=supply, heat_demand=1e6, flow=flow).outputs
    assert outputs.surplus == pytest.approx(0, abs=1e-6)
    assert outputs.unmet_demand == pytest.approx(0, abs=1e-6)


def test_surplus_is_what_the_water_gives_above_the_demand():
    """Twice the water at the demand of one: the rest is surplus, and nothing is unmet."""
    grid = closed_loop()
    flow = rate(grid, 2e6, 40.0)
    supply = gm.Stream(
        m_dot=gm.units.Quantity(flow, "kg/s"),
        T=gm.units.Quantity(373.15, "K"),
        p=gm.units.Quantity(6e5, "Pa"),
        fluid=gm.WATER,
    )
    outputs = grid(supply_in=supply, heat_demand=1e6, flow=flow).outputs
    assert outputs.surplus == pytest.approx(1e6)
    assert outputs.unmet_demand == 0


def test_a_user_on_an_open_circuit_has_no_surplus():
    """The return follows from the demand, so the water gives what was asked."""
    grid = HeatingGrid().set_params(
        "", {"minimum_return_temperature": gm.units.Quantity(313.15, "K")}
    )
    supply = gm.Stream(
        m_dot=gm.units.Quantity(10.0, "kg/s"),
        T=gm.units.Quantity(353.15, "K"),
        p=gm.units.Quantity(3e5, "Pa"),
        fluid=gm.WATER,
    )
    assert grid(supply_in=supply, heat_demand=1e5).outputs.surplus == 0
