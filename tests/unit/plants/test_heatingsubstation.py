"""Heating substation: building loop closure, demand caps, limits and balances."""

import math

import pytest

import gemini as gm
from gemini.modules import energy_balance, mass_balance
from gemini.plants import HeatingSubstation
from gemini.types import Stream
from tests.fixtures.balance import assert_plant_closes
from tests.fixtures.designs import with_values
from tests.fixtures.errors import raises
from tests.fixtures.reading import reading

CP = 4217.4
NETWORK = Stream(
    m_dot=gm.units.Quantity(2.0, "kg/s"),
    T=gm.units.Quantity(348.15, "K"),
    p=gm.units.Quantity(6e5, "Pa"),
)


def counterflow_effectiveness(ua, c_min, c_max):
    """Return the counterflow effectiveness [-] (Incropera et al., effectiveness-NTU)."""
    ntu, ratio = ua / c_min, c_min / c_max
    decay = math.exp(-ntu * (1 - ratio))
    return (1 - decay) / (1 - ratio * decay)


def test_met_demand_closes_the_building_loop(plants):
    """With the demand met the return follows from e C_min (T_network - T_return) = Q."""
    substation = plants["heating_substation"](with_values(HeatingSubstation()))
    result = substation(supply_in=NETWORK)
    out = reading(result)
    effectiveness = counterflow_effectiveness(2e4, 2 * CP, 3 * CP)
    assert out.heat_supplied == pytest.approx(1.5e5, rel=1e-12)
    assert reading(result.children["heat_exchanger"]).duty == pytest.approx(1.5e5, rel=1e-9)
    assert not result.children["consumer"].outputs.is_unmet and result.children[
        "consumer"
    ].outputs.unmet_demand == pytest.approx(0, abs=1e-6)
    assert out.return_out_T == pytest.approx(348.15 - 1.5e5 / (2 * CP), rel=1e-12)
    expected_return = 348.15 - 1.5e5 / (effectiveness * 2 * CP)
    assert result.children["consumer"].outlets.return_out.T == pytest.approx(
        expected_return, abs=1e-8
    )
    assert result.children["consumer"].inlets.supply_in.T == pytest.approx(
        expected_return + 1.5e5 / (3 * CP), abs=1e-8
    )
    valve = result.children["valve"]
    assert result.children["valve"].outputs.pressure_drop == valve.outputs.pressure_drop > 0
    assert result.outlets.return_out.p == pytest.approx(
        6e5 - result.children["valve"].outputs.pressure_drop - 2e4
    )
    assert energy_balance(substation, result)["relative_residual"] < 1e-12
    assert_plant_closes(substation, result)
    assert mass_balance(substation, result)["residual"] == 0
    assert list(result.leaves()) == ["valve", "pump", "heat_exchanger", "consumer"]


def test_large_demand_is_capped_at_the_return_floor(plants):
    """Beyond the exchanger's reach the return sits at the floor and the rest is unmet."""
    substation = plants["heating_substation"](with_values(HeatingSubstation()), demand=5e5)
    result = substation(supply_in=NETWORK)
    out = reading(result)
    effectiveness = counterflow_effectiveness(2e4, 2 * CP, 3 * CP)
    available = effectiveness * 2 * CP * (348.15 - 303.15)
    assert result.children["consumer"].outlets.return_out.T == pytest.approx(303.15, abs=1e-8)
    assert out.heat_supplied == pytest.approx(available, rel=1e-9)
    assert result.children["consumer"].outputs.is_unmet and result.children[
        "consumer"
    ].outputs.unmet_demand == pytest.approx(5e5 - available, rel=1e-9)


def test_stopped_or_cold_network_delivers_nothing(plants):
    """No network flow, or a supply below the return floor, leaves the demand unmet."""
    substation = plants["heating_substation"](with_values(HeatingSubstation()))
    result = substation(supply_in=NETWORK.with_(m_dot=0.0))
    stopped = reading(result)
    assert stopped.heat_supplied == 0
    assert result.children["consumer"].outputs.unmet_demand == 1.5e5
    assert result.children["valve"].outputs.pressure_drop == 0 and stopped.return_out_T == 348.15
    result = substation(supply_in=NETWORK.with_(T=300.15))
    assert reading(result).heat_supplied == 0
    assert result.children["consumer"].outlets.return_out.T == 300.15


def test_invalid_inputs_raise(plants):
    """A closed valve with flow and reverse flow raise; missing data names the parameters."""
    substation = plants["heating_substation"](with_values(HeatingSubstation()))
    substation.valve.opening = 0
    with pytest.raises(gm.errors.PhysicsError, match="closed valve"):
        substation(supply_in=NETWORK)
    substation.valve.opening = 0.8
    with pytest.raises(gm.errors.PhysicsError):
        substation(supply_in=NETWORK.with_(m_dot=-1.0))
    with raises(gm.errors.ValidationError, "missing_value", match="pump.flow"):
        with_values(HeatingSubstation())(supply_in=NETWORK)
