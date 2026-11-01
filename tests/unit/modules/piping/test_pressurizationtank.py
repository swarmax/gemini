"""Pressure re-anchoring of a closed circuit, alone and inside a small piping network."""

import pytest

import gemini as gm
from gemini.modules import Module, energy_balance, mass_balance
from gemini.modules.declarations import Inlet, Outlet, Output
from gemini.modules.piping import Mixer, Pipe, PressurizationTank, Splitter, Valve
from gemini.types import Stream
from tests.fixtures.air import air
from tests.fixtures.designs import with_values
from tests.fixtures.equivalence import assert_module_matches
from tests.fixtures.errors import raises
from tests.fixtures.reading import reading

RETURN = Stream(m_dot=10, T=323.15, p=1.2e5)


class Network(Module):
    """Two parallel branches, a pipe and a valve, joined and re-pressurised."""

    def __init__(self):
        """Declare the test network."""
        super().__init__()

        # Modules
        self.splitter = Splitter()
        self.pipe = with_values(Pipe()).set_params(
            "",
            {
                "length": 200,
                "inner_diameter": 0.08,
                "elevation_change": 0,
                "heat_transfer_coefficient": 2.0,
            },
        )
        self.valve = with_values(Valve()).set_params(
            "", {"flow_coefficient": {"value": 40, "unit": "m3/h/bar^0.5"}}
        )
        self.mixer = Mixer()
        self.tank = PressurizationTank()

        # Inlets
        self.fluid_in = Inlet(Stream)
        self.air_in = Inlet(Stream, kind="air")

        # Boundaries

        # Outputs
        self.pressure_correction = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Split, pass both branches, mix and hold the circuit pressure."""

        # Modules
        split = self.splitter(fluid_in=inlets.fluid_in, split_fraction=0.4)
        piped = self.pipe(fluid_in=split.outlets.branch1_out, air_in=inlets.air_in)
        throttled = self.valve(fluid_in=split.outlets.branch2_out, opening=0.8)
        mixed = self.mixer(
            branch1_in=piped.outlets.fluid_out, branch2_in=throttled.outlets.fluid_out
        )
        held = self.tank(
            fluid_in=mixed.outlets.fluid_out, pressure_setpoint={"value": 3, "unit": "bar"}
        )

        # Outputs
        self.pressure_correction = held.outputs.pressure_correction

        # Outlets
        outlet = held.outlets.fluid_out

        outlets = dict(fluid_out=outlet)
        return outlets


def test_outlet_leaves_at_the_setpoint():
    """The tank sets the pressure and reports the correction; flow and temperature pass."""
    result = PressurizationTank()(fluid_in=RETURN, pressure_setpoint={"value": 2, "unit": "bar"})
    outlet = result.outlets.fluid_out
    assert outlet.p == 2e5 and (outlet.m_dot, outlet.T) == (10, 323.15)
    assert result.outputs.pressure_correction == pytest.approx(0.8e5)
    relieved = reading(
        PressurizationTank()(fluid_in=RETURN, pressure_setpoint={"value": 1, "unit": "bar"})
    )
    assert relieved.pressure_correction == pytest.approx(-0.2e5)
    reverse = PressurizationTank()(fluid_in=RETURN.with_(m_dot=-1), pressure_setpoint=2e5)
    assert reverse.outlets.fluid_out.m_dot == -1
    assert energy_balance(PressurizationTank(), result)["residual"] == 0
    assert mass_balance(PressurizationTank(), result)["residual"] == 0


def test_invalid_setpoint_and_missing_command_raise():
    """A zero or missing pressure setpoint is rejected."""
    with pytest.raises(gm.errors.ValidationError):
        PressurizationTank()(fluid_in=RETURN, pressure_setpoint=0)
    with raises(gm.errors.ValidationError, "missing_value"):
        PressurizationTank()(fluid_in=RETURN)


def test_piping_network_closes_mass_and_energy():
    """A split, pipe, valve, mixer and tank network conserves mass and sensible energy."""
    network = Network()
    result = network(fluid_in=RETURN.with_(p=4e5), air_in=air(283.15))
    outlet = result.outlets.fluid_out
    assert outlet.m_dot == pytest.approx(10, rel=1e-15) and outlet.p == 3e5
    assert outlet.T < RETURN.T and reading(result.children["pipe"]).heat_loss > 0
    pipe_out = result.children["pipe"].outlets.fluid_out.p
    valve_out = result.children["valve"].outlets.fluid_out.p
    assert result.children["mixer"].outputs.pressure_imbalance == pytest.approx(
        abs(pipe_out - valve_out)
    )
    assert result.outputs.pressure_correction == pytest.approx(3e5 - min(pipe_out, valve_out))
    assert energy_balance(network, result)["relative_residual"] < 1e-12
    assert mass_balance(network, result)["relative_residual"] < 1e-15


def test_pressurization_tank_matches_traced():
    """Setpoint above and below the inlet pressure traces correctly."""
    rows = [
        dict(fluid_in=Stream(m_dot=10, T=323.15, p=p), pressure_setpoint=3e5)
        for p in (1.2e5, 3e5, 5e5)
    ]
    assert_module_matches(PressurizationTank(), rows)
