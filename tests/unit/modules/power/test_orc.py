"""ORC Lorenz-cycle power, first-law closure, capacity bypass, ambient and idle limits."""

import math

import pytest

import gemini as gm
from gemini.modules import energy_balance, mass_balance
from gemini.modules.power import ORC
from gemini.types import Stream
from tests.fixtures import si
from tests.fixtures.air import air
from tests.fixtures.equivalence import assert_module_matches
from tests.fixtures.reading import reading

BRINE = Stream(
    m_dot=gm.units.Quantity(100, "kg/s"),
    T=gm.units.Quantity(423.15, "K"),
    p=gm.units.Quantity(10e5, "Pa"),
)
"""Brine at 150 degC and 100 kg/s."""


def orc(**changes):
    """Return an air-cooled ORC with a 70 degC reinjection limit."""
    params = dict(
        minimum_brine_outlet_temperature={"value": 70, "unit": "degC"},
        pinch=5,
        carnot_fraction=0.5,
        condenser_approach=15,
        parasitic_fraction=0.15,
        capacity={"value": 5, "unit": "MW"},
    )
    return si.set_params(ORC(), "", params | changes)


def test_hand_calculated_lorenz_power():
    """Brine 150 -> 70 degC, T_c = 15 + 15 degC: W = 0.5 m cp ((T_a - T_b) - T_c ln(T_a/T_b))."""
    out = reading(orc()(fluid_in=BRINE, air_in=air({"value": 15, "unit": "degC"})))
    heat = 100 * 4217.4 * 80
    gross = 0.5 * 100 * 4217.4 * (80 - 303.15 * math.log(418.15 / 338.15))
    assert out.heat_input == pytest.approx(heat, rel=1e-12)
    assert out.gross_power == pytest.approx(gross, rel=1e-12)
    assert out.parasitic_power == pytest.approx(0.15 * gross, rel=1e-12)
    assert out.electricity_generated == pytest.approx(0.85 * gross, rel=1e-12)
    assert out.condenser_duty == pytest.approx(heat - gross, rel=1e-12)
    assert out.thermal_efficiency == pytest.approx(0.85 * gross / heat, rel=1e-12)
    assert out.fluid_out_T == pytest.approx(343.15) and out.condensing_temperature == 303.15
    assert not out.is_capped


def test_first_law_and_mass_closure():
    """Heat input = net power + heat loss, audited with the brine's cp."""
    module = orc()
    result = module(fluid_in=BRINE, air_in=air(288.15))
    out = reading(result)
    assert out.heat_input == pytest.approx(out.gross_power + out.condenser_duty, rel=1e-12)
    assert energy_balance(module, result)["relative_residual"] < 1e-12
    assert mass_balance(module, result)["residual"] == 0


def test_capacity_bypasses_brine_at_constant_cycle_efficiency():
    """A 1 MW cap processes part of the brine; the mixed outlet is warmer."""
    full = reading(orc()(fluid_in=BRINE, air_in=air(288.15)))
    module = orc(capacity={"value": 1, "unit": "MW"})
    result = module(fluid_in=BRINE, air_in=air(288.15))
    out = reading(result)
    assert out.is_capped and out.gross_power == pytest.approx(1e6, rel=1e-12)
    assert 343.15 < out.fluid_out_T < 423.15
    assert out.thermal_efficiency == pytest.approx(full.thermal_efficiency, rel=1e-12)
    assert energy_balance(module, result)["relative_residual"] < 1e-12


def test_hot_ambient_raises_condensing_and_outlet_temperatures():
    """At 55 degC ambient the pinch above T_c sets the brine outlet; power falls."""
    cool = reading(orc()(fluid_in=BRINE, air_in=air({"value": 15, "unit": "degC"})))
    hot = reading(orc()(fluid_in=BRINE, air_in=air({"value": 55, "unit": "degC"})))
    assert hot.fluid_out_T == pytest.approx(273.15 + 55 + 15 + 5)
    assert hot.electricity_generated < cool.electricity_generated


def test_idle_zero_flow_and_reverse_flow():
    """Brine below the outlet limit or no flow gives no power; reverse flow raises."""
    cold = BRINE.with_(T=340)
    result = orc()(fluid_in=cold, air_in=air(288.15))
    assert reading(result).electricity_generated == 0 and result.outputs.thermal_efficiency is None
    assert result.outlets.fluid_out.T == 340
    stopped = reading(orc()(fluid_in=BRINE.with_(m_dot=0), air_in=air(288.15)))
    assert stopped.heat_input == 0 and stopped.gross_power == 0 and not stopped.is_capped
    with pytest.raises(gm.errors.PhysicsError, match="fluid_in.m_dot = -1"):
        orc()(fluid_in=BRINE.with_(m_dot=-1), air_in=air(288.15))


def test_traced_call_matches_one_call_per_row():
    """Running, capped, idle (inlet too cold) and stopped rows trace and equal one call per row."""
    rows = [
        dict(
            fluid_in=Stream(
                m_dot=gm.units.Quantity(m_dot, "kg/s"),
                T=gm.units.Quantity(T, "K"),
                p=gm.units.Quantity(10e5, "Pa"),
            ),
            air_in=air(ambient),
        )
        for m_dot, T, ambient in [
            (100.0, 423.15, 288.15),
            (400.0, 423.15, 288.15),
            (100.0, 330.0, 288.15),
            (0.0, 423.15, 288.15),
            (50.0, 400.0, 303.15),
        ]
    ]
    assert_module_matches(orc(), rows)
