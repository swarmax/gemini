"""Sensible and latent cooling, dew-point test, return limits and balances."""

import pytest

import gemini as gm
from gemini.errors import PhysicsError, ValidationError
from gemini.modules import CoolingGrid, energy_balance, mass_balance
from gemini.physics import psychrometrics
from gemini.types import Stream
from tests.fixtures.equivalence import assert_module_matches
from tests.fixtures.errors import raises
from tests.fixtures.reading import reading

CP = 4217.4
SUPPLY = Stream(m_dot=2.0, T=280.15, p=3e5)
INDOOR = dict(indoor_temperature={"value": 24, "unit": "C"}, indoor_relative_humidity=0.5)
AVAILABLE = 2 * CP * 9


def _consumer():
    return CoolingGrid().set_params(
        "", {"maximum_return_temperature": {"value": 16, "unit": "C"}, "dew_point_margin": 3}
    )


def _call(consumer, supply=SUPPLY, sensible=5e4, latent=1e4, **indoor):
    return consumer(
        supply_in=supply,
        sensible_cooling_demand=sensible,
        latent_cooling_demand=latent,
        **(INDOOR | indoor),
    )


def test_met_loads_warm_the_return_and_close_the_balance():
    """Both loads are met below the dew point and warm the water by Q / (m_dot cp)."""
    consumer = _consumer()
    result = _call(consumer)
    out, return_out = reading(result), result.outlets.return_out
    assert out.heat_absorbed == pytest.approx(6e4)
    assert out.unmet_sensible == 0 and out.unmet_latent == 0
    assert not out.is_unmet
    assert out.return_out_T == pytest.approx(280.15 + 6e4 / (2 * CP)) == return_out.T
    assert out.dew_point == pytest.approx(psychrometrics.dew_point(297.15, 0.5))
    assert out.dew_point - 273.15 == pytest.approx(12.95, abs=0.01)
    assert return_out.m_dot == SUPPLY.m_dot and return_out.p == SUPPLY.p
    balance = energy_balance(consumer, result)
    assert balance["relative_residual"] < 1e-12
    assert mass_balance(consumer, result)["residual"] == 0


def test_short_capacity_serves_the_sensible_load_first():
    """At the return limit the sensible load is met first and the latent load takes the rest."""
    consumer = _consumer()
    out = reading(_call(consumer, sensible=7e4, latent=2e4))
    assert out.unmet_sensible == 0
    assert out.unmet_latent == pytest.approx(9e4 - AVAILABLE) and out.is_unmet
    assert out.heat_absorbed == pytest.approx(AVAILABLE) and out.return_out_T == 289.15
    result = _call(consumer, sensible=1e5, latent=2e4)
    assert result.outputs.unmet_sensible == pytest.approx(1e5 - AVAILABLE)
    assert result.outputs.unmet_latent == 2e4
    assert energy_balance(consumer, result)["relative_residual"] < 1e-12


def test_supply_above_the_dew_point_margin_leaves_the_latent_load_unmet():
    """A supply warmer than T_dew - margin does not dehumidify; the sensible load is still met."""
    consumer = _consumer()
    threshold = psychrometrics.dew_point(297.15, 0.5) - 3
    out = reading(_call(consumer, supply=SUPPLY.with_(T=threshold + 0.01), sensible=3e4))
    assert out.unmet_latent == 1e4 and out.unmet_sensible == 0
    assert out.heat_absorbed == pytest.approx(3e4)
    assert out.is_unmet
    out = reading(_call(consumer, supply=SUPPLY.with_(T=threshold - 0.01), sensible=3e4))
    assert out.unmet_latent == 0 and not out.is_unmet
    assert out.heat_absorbed == pytest.approx(4e4)


def test_indoor_temperature_limits_the_return():
    """The water cannot return warmer than the indoor air; a warm supply absorbs nothing."""
    consumer = _consumer()
    out = reading(_call(consumer, sensible=1e6, indoor_temperature={"value": 12, "unit": "C"}))
    assert out.return_out_T == 285.15 and out.heat_absorbed == pytest.approx(2 * CP * 5)
    out = reading(_call(consumer, supply=SUPPLY.with_(T=300.0)))
    assert out.heat_absorbed == 0 and out.return_out_T == 300.0 and out.unmet_sensible == 5e4


def test_zero_flow_and_zero_demand():
    """No flow absorbs nothing; no demand leaves the stream unchanged and nothing unmet."""
    consumer = _consumer()
    result = _call(consumer, supply=SUPPLY.with_(m_dot=0))
    assert reading(result).heat_absorbed == 0 and result.outlets.return_out.T == SUPPLY.T
    assert result.outputs.unmet_sensible == 5e4 and result.outputs.unmet_latent == 1e4
    assert energy_balance(consumer, result)["relative_residual"] < 1e-12
    out = reading(_call(consumer, sensible=0, latent=0))
    assert out.heat_absorbed == 0 and not out.is_unmet and out.return_out_T == SUPPLY.T


def test_invalid_inputs_raise():
    """Reverse flow, dry air, negative loads and missing values are rejected."""
    consumer = _consumer()
    with pytest.raises(PhysicsError, match="supply_in.m_dot = -1"):
        _call(consumer, supply=SUPPLY.with_(m_dot=-1))
    with pytest.raises(ValidationError):
        _call(consumer, indoor_relative_humidity=0)
    with pytest.raises(ValidationError):
        _call(consumer, latent=-1)
    with pytest.raises(ValidationError):
        consumer.set_params("", {"dew_point_margin": -1})
    with raises(ValidationError, "missing_value"):
        consumer(supply_in=SUPPLY, sensible_cooling_demand=1e4, latent_cooling_demand=0)


def test_traced_call_matches_one_call_per_row():
    """Met, short, humid (no latent), no-demand and stopped rows trace and equal per-row calls."""
    rows = [
        dict(
            supply_in=Stream(m_dot=m_dot, T=T, p=3e5),
            sensible_cooling_demand=sensible,
            latent_cooling_demand=latent,
            indoor_temperature=297.15,
            indoor_relative_humidity=humidity,
        )
        for m_dot, T, sensible, latent, humidity in [
            (2.0, 280.15, 5e4, 1e4, 0.5),
            (2.0, 280.15, 7e4, 2e4, 0.5),
            (2.0, 288.0, 5e4, 1e4, 0.5),
            (2.0, 280.15, 0.0, 0.0, 0.5),
            (0.0, 280.15, 5e4, 1e4, 0.5),
            (2.0, 280.15, 5e4, 1e4, 1.0),
            (2.0, 295.0, 5e4, 1e4, 0.8),
        ]
    ]
    assert_module_matches(_consumer(), rows)


def test_a_closed_loop_reports_the_cold_above_the_demand():
    """More water than the load takes up to the fixed return: the rest is surplus."""
    grid = CoolingGrid().set_params(
        "", {"return_temperature": 301.15, "return_pressure": 4e5, "dew_point_margin": 1.0}
    )
    grid.fluid = gm.WATER
    flow = 2e6 / (grid.fluid.properties(0, 0).cp_l * 8.0)
    supply = gm.Stream(m_dot=flow, T=293.15, p=4e5, fluid=gm.WATER)
    outputs = grid(
        supply_in=supply,
        flow=flow,
        sensible_cooling_demand=1e6,
        latent_cooling_demand=0.0,
        indoor_temperature=303.15,
        indoor_relative_humidity=0.5,
    ).outputs
    assert outputs.surplus == pytest.approx(1e6)
    assert outputs.unmet_sensible == 0
