"""Cooling substation: building loop closure, dehumidification, limits and balances."""

import math

import pytest

import gemini as gm
from gemini.modules import energy_balance, mass_balance
from gemini.plants import CoolingSubstation
from gemini.types import Stream
from tests.fixtures.balance import assert_plant_closes
from tests.fixtures.designs import with_values
from tests.fixtures.reading import reading

CP = 4217.4
NETWORK = Stream(
    m_dot=gm.units.Quantity(3.0, "kg/s"),
    T=gm.units.Quantity(279.15, "K"),
    p=gm.units.Quantity(6e5, "Pa"),
)


def counterflow_effectiveness(ua, c_min, c_max):
    """Return the counterflow effectiveness [-] (Incropera et al., effectiveness-NTU)."""
    ntu, ratio = ua / c_min, c_min / c_max
    decay = math.exp(-ntu * (1 - ratio))
    return (1 - decay) / (1 - ratio * decay)


def test_met_loads_close_the_building_loop(plants):
    """Sensible plus latent load enter the water; e C_min (T_return - T_network) = Q."""
    substation = plants["cooling_substation"](with_values(CoolingSubstation()))
    result = substation(supply_in=NETWORK)
    out = reading(result)
    effectiveness = counterflow_effectiveness(3e4, 3 * CP, 4 * CP)
    assert reading(result.children["consumer"]).heat_absorbed == pytest.approx(7e4, rel=1e-12)
    assert reading(result.children["heat_exchanger"]).duty == pytest.approx(7e4, rel=1e-9)
    assert not result.children["consumer"].outputs.is_unmet
    assert out.return_out_T == pytest.approx(279.15 + 7e4 / (3 * CP), rel=1e-12)
    expected_return = 279.15 + 7e4 / (effectiveness * 3 * CP)
    assert result.children["consumer"].outlets.return_out.T == pytest.approx(
        expected_return, abs=1e-8
    )
    assert result.children["consumer"].inlets.supply_in.T == pytest.approx(
        expected_return - 7e4 / (4 * CP), abs=1e-8
    )
    assert (
        result.children["consumer"].inlets.supply_in.T
        < result.children["consumer"].outputs.dew_point - 1.0
    )
    assert energy_balance(substation, result)["relative_residual"] < 1e-12
    assert_plant_closes(substation, result)
    assert mass_balance(substation, result)["residual"] == 0


def test_warm_network_cannot_dehumidify(plants):
    """A supply too warm for the dew-point margin leaves the latent load unmet."""
    substation = plants["cooling_substation"](with_values(CoolingSubstation()))
    result = substation(supply_in=NETWORK.with_(T=284.15))
    assert (
        result.children["consumer"].inlets.supply_in.T
        > result.children["consumer"].outputs.dew_point - 1.0
    )
    assert (
        result.children["consumer"].outputs.unmet_latent == 1e4
        and result.children["consumer"].outputs.is_unmet
    )
    assert reading(result.children["consumer"]).heat_absorbed == pytest.approx(6e4, rel=1e-12)
    assert result.children["consumer"].outputs.unmet_sensible == pytest.approx(0, abs=1e-6)


def test_large_load_is_capped_at_the_return_limit(plants):
    """Beyond the exchanger's reach the return sits at the 18 degC limit."""
    substation = plants["cooling_substation"](with_values(CoolingSubstation()), sensible=5e5)
    result = substation(supply_in=NETWORK)
    effectiveness = counterflow_effectiveness(3e4, 3 * CP, 4 * CP)
    available = effectiveness * 3 * CP * (291.15 - 279.15)
    assert result.children["consumer"].outlets.return_out.T == pytest.approx(291.15, abs=1e-8)
    assert reading(result.children["consumer"]).heat_absorbed == pytest.approx(available, rel=1e-9)
    assert result.children["consumer"].outputs.unmet_sensible == pytest.approx(
        5e5 - available, rel=1e-9
    )
    assert result.children["consumer"].outputs.unmet_latent == 1e4


def test_stopped_network_and_invalid_inputs(plants):
    """No network flow absorbs nothing; reverse flow raises."""
    substation = plants["cooling_substation"](with_values(CoolingSubstation()))
    result = substation(supply_in=NETWORK.with_(m_dot=0.0))
    assert (
        reading(result.children["consumer"]).heat_absorbed == 0
        and result.children["consumer"].outputs.unmet_sensible == 6e4
    )
    with pytest.raises(gm.errors.PhysicsError):
        substation(supply_in=NETWORK.with_(m_dot=-1.0))


def test_loop_without_a_steady_state_raises(plants):
    """At the dew-point threshold the on/off latent test leaves no fixed point of the loop."""
    substation = plants["cooling_substation"](with_values(CoolingSubstation()), latent=5e4)
    with pytest.raises(gm.errors.PhysicsError, match="did not converge"):
        substation(supply_in=NETWORK.with_(T=281.15))
