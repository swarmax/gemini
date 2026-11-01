"""Doublet thermal breakthrough and production temperature decline."""

import math

import pytest

import gemini as gm
from gemini.modules import Module, energy_balance, mass_balance
from gemini.modules.declarations import Inlet, Outlet, Output
from gemini.modules.heating import ElectricBoiler
from gemini.modules.subsurface import ThermalDecline
from gemini.types import Stream
from gemini.types.fluid import BRINE as DEFAULT_FLUID
from tests.fixtures.equivalence import assert_function_matches, assert_same_error
from tests.fixtures.reading import reading

STREAM = Stream(
    m_dot=gm.units.Quantity(50, "kg/s"),
    T=gm.units.Quantity(353.15, "K"),
    p=gm.units.Quantity(2e7, "Pa"),
)
WATER = 1000 * 4217.4
AQUIFER = 0.2 * WATER + 0.8 * 2.5e6
BREAKTHROUGH = math.pi * 1000**2 * 50 * AQUIFER / (3 * WATER)


def decline():
    """Return a configured decline model with a 313.15 K injection temperature."""
    module = ThermalDecline().set_params(
        "",
        {
            "well_spacing": gm.units.Quantity(1000, "m"),
            "aquifer_thickness": gm.units.Quantity(50, "m"),
            "porosity": 0.2,
            "rock_volumetric_heat_capacity": gm.units.Quantity(2.5e6, "J/m3/K"),
        },
    )
    module.injection_temperature = 313.15
    return module


class Producer(Module):
    """Production branch: thermal decline followed by a booster heater."""

    def __init__(self):
        """Declare the test composite."""
        super().__init__()

        # Modules
        self.decline = decline()
        self.heater = ElectricBoiler().set_params(
            "", {"capacity": gm.units.Quantity(1e7, "W"), "efficiency": 0.9}
        )

        # Inlets
        self.sandface = Inlet(Stream)

        # Outputs
        self.temperature_drop = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Pass the produced stream through both children."""

        # Modules
        declined = self.decline(fluid_in=inlets.sandface)
        heated = self.heater(fluid_in=declined.outlets.fluid_out, temperature_setpoint=300)

        # Outputs
        self.temperature_drop = declined.outputs.temperature_drop

        # Outlets
        outlet = heated.outlets.fluid_out

        outlets = dict(fluid_out=outlet)
        return outlets


def test_plain_call_uses_the_initial_state():
    """Without injected volume the reservoir temperature passes; V_B / Q is the G-S time."""
    module = decline()
    result = module(fluid_in=STREAM)
    assert module.initial_state() == {"injected_volume": 0}
    assert result.outlets.fluid_out == STREAM
    assert result.outputs.temperature_drop == 0
    assert result.outputs.breakthrough_time == pytest.approx(BREAKTHROUGH / (50 / 1000))
    assert result.outputs.breakthrough_time / 3.15576e7 == pytest.approx(22.37, abs=0.01)


def test_two_steps_accumulate_the_produced_volume():
    """Each step adds Q dt; the temperature uses the start-of-step volume."""
    module = decline()
    state, result = module.step(None, 3600, {"fluid_in": STREAM})
    assert state == {"injected_volume": pytest.approx(50 / 1000 * 3600)}
    state, result = module.step(state, 3600, {"fluid_in": STREAM})
    assert state["injected_volume"] == pytest.approx(2 * 50 / 1000 * 3600)
    assert reading(result).fluid_out_T == STREAM.T


def test_decline_after_breakthrough_is_the_dipole_cold_share():
    """At three breakthrough volumes half the produced flow is at the injection temperature."""
    module = decline()
    state, result = module.step({"injected_volume": 3 * BREAKTHROUGH}, 3600, {"fluid_in": STREAM})
    assert result.outputs.temperature_drop == pytest.approx(0.5 * (353.15 - 313.15), rel=1e-12)
    assert result.outlets.fluid_out.T == pytest.approx(333.15)
    assert result.outlets.fluid_out.p == STREAM.p and result.outlets.fluid_out.m_dot == STREAM.m_dot
    drops = [
        module.step({"injected_volume": ratio * BREAKTHROUGH}, 60, {"fluid_in": STREAM})[
            1
        ].outputs.temperature_drop
        for ratio in (0.99, 1.01, 2, 10, 100)
    ]
    assert drops[0] == 0 and drops == sorted(drops) and drops[-1] < 40


def test_balances_show_the_boundary_correction():
    """Mass passes unchanged; the energy residual is the documented boundary correction."""
    module = decline()
    _, result = module.step({"injected_volume": 3 * BREAKTHROUGH}, 3600, {"fluid_in": STREAM})
    assert mass_balance(module, result)["residual"] == 0
    residual = energy_balance(module, result)["residual"]
    assert residual == pytest.approx(50 * 4217.4 * 20, rel=1e-9)


def test_zero_and_reverse_flow():
    """Zero flow keeps the state and has no breakthrough time; reverse flow is rejected."""
    module = decline()
    state, result = module.step({"injected_volume": 1e7}, 3600, {"fluid_in": STREAM.with_(m_dot=0)})
    assert state == {"injected_volume": 1e7} and result.outputs.breakthrough_time is None
    with pytest.raises(gm.errors.PhysicsError, match="fluid_in.m_dot = -1"):
        module(fluid_in=STREAM.with_(m_dot=-1))
    with pytest.raises(gm.errors.ValidationError):
        module.set_params("", {"porosity": 1})


def test_composite_step_advances_the_decline():
    """A plant composite steps the decline through its forward."""
    plant = Producer()
    assert plant.initial_state() == {"decline": {"injected_volume": 0}}
    state, _ = plant.step(None, 86400, {"sandface": STREAM})
    state, result = plant.step(state, 86400, {"sandface": STREAM})
    assert state["decline"]["injected_volume"] == pytest.approx(2 * 50 / 1000 * 86400)
    assert result.outputs.temperature_drop == 0
    late = {"decline": {"injected_volume": 3 * BREAKTHROUGH}}
    _, result = plant.step(late, 86400, {"sandface": STREAM})
    assert result.outputs.temperature_drop == pytest.approx(20)


def test_decline_arithmetic_matches_on_arrays():
    """The liquid flow, breakthrough volume and drop agree on arrays; reverse flow raises alike."""
    module = decline()

    def numbers(m_dot, T, p):
        inlet = Stream._si(m_dot=m_dot, T=T, p=p, fluid=DEFAULT_FLUID)
        return dict(
            flow=module._liquid_flow(inlet),
            volume=module._breakthrough_volume(inlet),
            drop=module._temperature_drop(inlet),
        )

    rows = [(50.0, 353.15, 2e7), (0.0, 353.15, 2e7), (5.0, 330.0, 1e6)]
    assert_function_matches(numbers, rows)
    assert_same_error(numbers, rows + [(-1.0, 353.15, 2e7)], gm.errors.PhysicsError)
