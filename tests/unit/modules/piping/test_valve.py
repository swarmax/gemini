"""Valve sizing equation, inherent characteristics, closed valve and limits."""

import pytest

import gemini as gm
from gemini.modules import energy_balance, mass_balance
from gemini.modules.piping import Valve
from gemini.types import Fluid, Stream
from tests.fixtures.designs import with_values
from tests.fixtures.equivalence import assert_module_matches

KV = 100 / 3600 / 1e5**0.5
"""Flow coefficient [m3/s/Pa^0.5] of a catalogue Kv = 100 m3/h/bar^0.5."""

STREAM = Stream(
    flow={"value": 36, "unit": "m3/h"},
    T=gm.units.Quantity(353.15, "K"),
    p=gm.units.Quantity(20e5, "Pa"),
)


def valve(**changes):
    """Return a Kv 100 equal-percentage valve."""
    return with_values(Valve()).set_params(
        "", {"flow_coefficient": {"value": 100, "unit": "m3/h/bar^0.5"}} | changes
    )


def test_fully_open_valve_matches_the_catalogue_kv():
    """36 m3/h of water through Kv 100 drops (36/100)^2 bar, isenthalpically."""
    result = valve()(fluid_in=STREAM, opening=1)
    assert result.outputs.effective_flow_coefficient == pytest.approx(KV, rel=1e-14)
    assert result.outputs.pressure_drop == pytest.approx(0.36**2 * 1e5, rel=1e-12)
    outlet = result.outlets.fluid_out
    assert outlet.T == STREAM.T and outlet.m_dot == STREAM.m_dot
    assert energy_balance(valve(), result)["residual"] == 0
    assert mass_balance(valve(), result)["residual"] == 0


def test_inherent_characteristics():
    """Equal percentage gives R^(h-1), linear 1/R + (1-1/R) h, and dp scales with 1/Kv^2."""
    equal = valve()(fluid_in=STREAM, opening=0.5).outputs
    assert equal.effective_flow_coefficient == pytest.approx(KV * 50**-0.5)
    assert equal.pressure_drop == pytest.approx(0.36**2 * 1e5 * 50)
    linear = valve(characteristic="linear", rangeability=20)(fluid_in=STREAM, opening=0.5).outputs
    assert linear.effective_flow_coefficient == pytest.approx(KV * (0.05 + 0.95 * 0.5))
    for module in (valve(), valve(characteristic="linear")):
        coefficients = [
            module(fluid_in=STREAM.with_(m_dot=1), opening=h).outputs.effective_flow_coefficient
            for h in (0.01, 0.3, 0.6, 1)
        ]
        assert coefficients == sorted(coefficients)


def test_density_enters_the_sizing_equation():
    """The sizing equation dp = rho / 1000 (q / Kv)^2 gives a denser brine less drop."""
    brine = Fluid(density=gm.units.Quantity(1050, "kg/m3"))
    stream = Stream(
        m_dot=gm.units.Quantity(STREAM.m_dot, "kg/s"),
        T=gm.units.Quantity(353.15, "K"),
        p=gm.units.Quantity(5e5, "Pa"),
        fluid=brine,
    )
    drop = valve()(fluid_in=stream, opening=1).outputs.pressure_drop
    assert drop == pytest.approx(1.05 * (10 / 1050 / KV) ** 2, rel=1e-12)


def test_closed_valve():
    """A closed valve passes zero flow with no drop and rejects any flow."""
    stopped = valve()(fluid_in=STREAM.with_(m_dot=0), opening=0).outputs
    assert stopped.pressure_drop == 0 and stopped.effective_flow_coefficient == 0
    with pytest.raises(gm.errors.PhysicsError, match="valve: fluid_in.m_dot = 10.0 kg/s"):
        valve()(fluid_in=STREAM, opening=0)


def test_invalid_inputs_raise():
    """Reverse flow, free gas and a drop larger than the inlet pressure are rejected."""
    with pytest.raises(gm.errors.PhysicsError, match="reverse flow"):
        valve()(fluid_in=STREAM.with_(m_dot=-1), opening=1)
    with pytest.raises(gm.errors.PhysicsError, match="gas_mass_fraction"):
        valve()(fluid_in=STREAM.with_(fluid=Fluid(gas_mass_fraction=0.01)), opening=1)
    with pytest.raises(gm.errors.PhysicsError, match="pressure drop"):
        valve()(fluid_in=STREAM, opening=0.05)
    with pytest.raises(gm.errors.ValidationError):
        valve(rangeability=1)
    with pytest.raises(gm.errors.ValidationError):
        valve()(fluid_in=STREAM, opening=1.5)


def test_valve_matches_traced():
    """Both characteristics, a closed valve with no flow and a stopped inlet trace correctly."""
    rows = [
        dict(
            fluid_in=Stream(
                m_dot=gm.units.Quantity(m_dot, "kg/s"),
                T=gm.units.Quantity(353.15, "K"),
                p=gm.units.Quantity(20e5, "Pa"),
            ),
            opening=opening,
        )
        for m_dot, opening in [(10, 1), (10, 0.5), (1, 0.01), (0, 0), (0, 0.3)]
    ]
    for module in (valve(), valve(characteristic="linear", rangeability=20)):
        assert_module_matches(module, rows)
