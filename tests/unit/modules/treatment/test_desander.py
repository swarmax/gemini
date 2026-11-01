"""Desander pressure loss, sand removal and limits."""

import pytest

import gemini as gm
from gemini.modules._utils.balance import energy_balance, mass_balance
from gemini.modules.treatment import Desander
from gemini.types.flows import Stream
from tests.fixtures.equivalence import assert_module_matches
from tests.fixtures.errors import raises

INLET = Stream(m_dot=20, T=350, p=1e6)


def desander():
    """Return a desander rated 1 bar at 40 kg/s that removes 90 % of the sand."""
    return Desander().set_params(
        "", {"separation_efficiency": 0.9, "nominal_pressure_drop": 1e5, "nominal_mass_flow": 40}
    )


def test_hand_computed_removal_and_loss():
    """Quadratic loss and removal from the liquid volume flow, with mg/l accepted."""
    module = desander()
    result = module(fluid_in=INLET, sand_concentration={"value": 50, "unit": "mg/l"})
    out = result.outputs
    assert out.pressure_drop == 25000
    removed = result.outlets.waste_out.m_dot
    assert result.outlets.fluid_out == INLET.with_(m_dot=INLET.m_dot - removed, p=1e6 - 25000)
    assert result.outlets.waste_out.m_dot == out.sand_removal_rate
    assert out.sand_removal_rate == pytest.approx(0.9 * 0.05 * 0.02)
    assert out.residual_sand_concentration == pytest.approx(0.005)
    assert mass_balance(module, result)["residual"] == 0
    assert energy_balance(module, result)["relative_residual"] < 1e-12


def test_limits():
    """Zero flow removes nothing; reverse flow and a loss above inlet pressure raise."""
    module = desander()
    stopped = module(fluid_in=INLET.with_(m_dot=0), sand_concentration=0.05).outputs
    assert stopped.pressure_drop == 0 and stopped.sand_removal_rate == 0
    with pytest.raises(gm.errors.PhysicsError, match="fluid_in.m_dot"):
        module(fluid_in=INLET.with_(m_dot=-1), sand_concentration=0.05)
    with pytest.raises(gm.errors.PhysicsError, match="pressure_drop"):
        module(fluid_in=INLET.with_(m_dot=200, p=2e5), sand_concentration=0.05)
    with pytest.raises(gm.errors.ValidationError):
        module(fluid_in=INLET, sand_concentration=-1)
    with raises(gm.errors.ValidationError, "missing_value"):
        Desander()(fluid_in=INLET, sand_concentration=0.05)


def test_desander_matches_traced():
    """The cyclone loss and sand removal trace and equal one call per row."""
    rows = [
        dict(fluid_in=Stream(m_dot=m_dot, T=350, p=1e6), sand_concentration=sand)
        for m_dot, sand in [(0, 0.05), (20, 0.05), (40, 0.001), (60, 0.2)]
    ]
    assert_module_matches(desander(), rows)
