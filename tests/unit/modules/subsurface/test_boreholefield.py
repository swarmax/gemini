"""Closed-loop borehole field: effectiveness, lumped ground state and balances."""

import math

import pytest

import gemini as gm
from gemini import ops
from gemini.modules import Module, energy_balance, mass_balance
from gemini.modules.declarations import Inlet, Outlet
from gemini.modules.heating import ElectricBoiler
from gemini.modules.subsurface import BoreholeField
from gemini.types import Stream
from gemini.types.fluid import BRINE as DEFAULT_FLUID
from tests.fixtures.equivalence import assert_function_matches, assert_same_error
from tests.fixtures.errors import raises
from tests.fixtures.reading import reading

BRINE = Stream(
    m_dot=gm.units.Quantity(3, "kg/s"),
    T=gm.units.Quantity(273.15, "K"),
    p=gm.units.Quantity(3e5, "Pa"),
)
CP = 4217.4
DAY = 86400.0


def field():
    """Return a ten-borehole field of 150 m at 6 m spacing."""
    return BoreholeField().set_params(
        "",
        {
            "borehole_count": 10,
            "borehole_depth": gm.units.Quantity(150, "m"),
            "borehole_radius": gm.units.Quantity(0.075, "m"),
            "borehole_spacing": gm.units.Quantity(6, "m"),
            "borehole_resistance": gm.units.Quantity(0.1, "m.K/W"),
            "ground_conductivity": gm.units.Quantity(2.0, "W/m/K"),
            "ground_volumetric_heat_capacity": gm.units.Quantity(2.2e6, "J/m3/K"),
            "undisturbed_ground_temperature": gm.units.Quantity(283.15, "K"),
        },
    )


def hand_effectiveness(m_dot):
    """Return the hand-computed loop effectiveness [-] at a mass flow [kg/s]."""
    r_e, r_b = 6 / math.sqrt(math.pi), 0.075
    x = (r_b / r_e) ** 2
    cell = (math.log(r_e / r_b) / (1 - x) ** 2 - 1 / (2 * (1 - x)) - 0.25) / (2 * math.pi * 2.0)
    return 1 - math.exp(-1500 / (0.1 + cell) / (m_dot * CP))


def surroundings():
    """Return the hand-computed field-to-surroundings conductance [W/K]."""
    diameter = 2 * math.sqrt(360 / math.pi)
    return 2.0 * 2 * math.pi * 150 / math.log(4 * 150 / diameter)


class HeatPumpLoop(Module):
    """Ground loop followed by a heater standing in for the heat pump evaporator return."""

    def __init__(self):
        """Declare the test composite."""
        super().__init__()

        # Modules
        self.field = field()
        self.heater = ElectricBoiler().set_params(
            "", {"capacity": gm.units.Quantity(1e5, "W"), "efficiency": 0.9}
        )

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Pass the brine through the field and the heater."""

        # Modules
        ground = self.field(fluid_in=inlets.fluid_in)
        heated = self.heater(fluid_in=ground.outlets.fluid_out, temperature_setpoint=280)

        # Outlets
        outlet = heated.outlets.fluid_out

        outlets = dict(fluid_out=outlet)
        return outlets


def test_plain_call_extracts_with_the_loop_effectiveness():
    """At the undisturbed ground temperature Q = eps m_dot cp (T_u - T_in)."""
    module = field()
    result = module(fluid_in=BRINE)
    out = reading(result)
    rate = hand_effectiveness(3) * 3 * CP * 10
    assert module.initial_state() == {"ground_temperature_change": 0}
    assert out.heat_extraction_rate == pytest.approx(rate, rel=1e-12)
    assert out.fluid_out_T == pytest.approx(273.15 + rate / (3 * CP))
    assert out.fluid_mean_temperature == pytest.approx((273.15 + out.fluid_out_T) / 2)
    assert out.ground_temperature == 283.15 and out.heat_absorbed == out.heat_extraction_rate
    assert out.heat_loss == 0
    assert energy_balance(module, result)["relative_residual"] < 1e-12
    assert mass_balance(module, result)["residual"] == 0


def test_two_steps_follow_the_exact_ground_response():
    """Each step solves the linear ground balance exactly for a constant inlet."""
    module = field()
    state, _ = module.step(None, 30 * DAY, {"fluid_in": BRINE})
    exchange = hand_effectiveness(3) * 3 * CP
    total = exchange + surroundings()
    equilibrium = exchange * (273.15 - 283.15) / total
    decay = math.exp(-total * 30 * DAY / (2.2e6 * 360 * 150))
    assert state["ground_temperature_change"] == pytest.approx(equilibrium * (1 - decay))
    state, result = module.step(state, 30 * DAY, {"fluid_in": BRINE})
    assert result.outputs.ground_temperature == pytest.approx(283.15 + equilibrium * (1 - decay))
    double, _ = module.step(None, 60 * DAY, {"fluid_in": BRINE})
    assert state["ground_temperature_change"] == pytest.approx(
        double["ground_temperature_change"], rel=1e-12
    )


def test_heat_rejection_recovery_and_zero_flow():
    """Warm inlets reject heat as heat_loss; without flow the ground recovers on its own."""
    module = field()
    result = module(fluid_in=BRINE.with_(T=303.15))
    assert reading(result).heat_extraction_rate < 0 and reading(result).heat_absorbed == 0
    assert reading(result).heat_loss == -reading(result).heat_extraction_rate
    assert energy_balance(module, result)["relative_residual"] < 1e-12
    still = BRINE.with_(m_dot=0)
    state, result = module.step({"ground_temperature_change": -2.0}, 365 * DAY, {"fluid_in": still})
    decay = math.exp(-surroundings() * 365 * DAY / (2.2e6 * 360 * 150))
    assert state["ground_temperature_change"] == pytest.approx(-2.0 * decay)
    assert result.outlets.fluid_out.T == still.T and reading(result).heat_extraction_rate == 0


def test_invalid_flow_and_geometry():
    """Reverse flow and geometries outside the cell and shape-factor ranges are rejected."""
    with pytest.raises(gm.errors.PhysicsError, match="fluid_in.m_dot = -1"):
        field()(fluid_in=BRINE.with_(m_dot=-1))
    with raises(gm.errors.ValidationError, "invalid_design", match="field geometry rejected"):
        field().set_params("", {"borehole_spacing": gm.units.Quantity(0.1, "m")})(fluid_in=BRINE)
    shallow = field().set_params(
        "", {"borehole_count": 400, "borehole_depth": gm.units.Quantity(10, "m")}
    )
    with raises(gm.errors.ValidationError, "invalid_design", match="expected ln"):
        shallow.step(None, DAY, {"fluid_in": BRINE})


def test_composite_step_advances_the_ground():
    """A composite steps the field through its forward."""
    loop = HeatPumpLoop()
    state, _ = loop.step(None, 7 * DAY, {"fluid_in": BRINE})
    state, result = loop.step(state, 7 * DAY, {"fluid_in": BRINE})
    assert state["field"]["ground_temperature_change"] < 0
    assert (
        0
        < reading(result.children["field"]).heat_extraction_rate
        < hand_effectiveness(3) * 3 * CP * 10
    )


def test_field_arithmetic_matches_on_arrays():
    """The loop conductance, surroundings and ground heat capacity agree on arrays."""
    module = field()

    @ops.physics
    def numbers(m_dot, T, p):
        inlet = Stream._si(m_dot=m_dot, T=T, p=p, fluid=DEFAULT_FLUID)
        return dict(
            exchange=module._effective_conductance(inlet),
            surroundings=module._surroundings_conductance(),
            capacity=module._ground_heat_capacity(),
        )

    rows = [(3.0, 273.15, 3e5), (0.0, 273.15, 3e5), (0.05, 300.0, 3e5)]
    assert_function_matches(numbers, rows)
    assert_same_error(numbers, rows + [(-1.0, 273.15, 3e5)], gm.errors.PhysicsError)


def test_zero_flow_does_not_evaluate_the_cell_geometry():
    """A cell no wider than the borehole is bad design data only where the loop flows."""
    module = field().set_params("", {"borehole_spacing": gm.units.Quantity(0.1, "m")})
    conductance = ops.physics(module._effective_conductance)
    assert conductance(BRINE.with_(m_dot=0)) == 0
    with raises(gm.errors.ValidationError, "invalid_design", match="field geometry rejected"):
        conductance(BRINE)
