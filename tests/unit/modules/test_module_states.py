"""Declared states: initial values, leaf and composite steps, and their validation."""

import pandas as pd
import pytest

import gemini as gm
from gemini.modules import Module
from gemini.modules.declarations import Control, Inlet, Outlet, Output, Parameter, State
from gemini.types import Duty, Energy, Stream, Temperature
from gemini.types.bindings import Binding, ModuleBindings
from tests.fixtures.errors import raises
from tests.fixtures.reading import reading

STREAM = Stream(
    m_dot=gm.units.Quantity(1, "kg/s"),
    T=gm.units.Quantity(350, "K"),
    p=gm.units.Quantity(1e6, "Pa"),
)


class Tank(Module):
    """Mixed tank whose temperature relaxes towards the inlet temperature."""

    def __init__(self):
        """Declare the test module."""
        super().__init__()

        # Parameters
        self.heat_capacity = Parameter(float, default=4217.4 * 100, gt=0)

        # Inlets
        self.fluid_in = Inlet(Stream)

        # States
        self.temperature = State(Temperature, default=300)

        # Outputs
        self.duty = Output(Duty)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Leave at the tank temperature of the start of the step."""

        # Outlets
        outlet = inlets.fluid_in.with_(T=self.temperature)

        outlets = dict(fluid_out=outlet)
        self.duty = self._duty(inlets.fluid_in)
        return outlets

    def _advance_states(self, inlets, outlets, dt):
        return {
            "temperature": self.temperature + self._duty(inlets.fluid_in) * dt / self.heat_capacity
        }

    def _duty(self, inlet):
        return inlet.m_dot * 4217.4 * (inlet.T - self.temperature)


class Line(Module):
    """Two tanks in series."""

    def __init__(self):
        """Declare the test module."""
        super().__init__()

        # Modules
        self.first = Tank()
        self.second = Tank()

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Pass the stream through both tanks."""

        # Modules
        first = self.first(fluid_in=inlets.fluid_in)
        second = self.second(fluid_in=first.outlets.fluid_out)

        # Outlets
        outlet = second.outlets.fluid_out

        outlets = dict(fluid_out=outlet)
        return outlets


class Integrator(Module):
    """Accumulate a commanded rate over time."""

    def __init__(self):
        """Declare the test module."""
        super().__init__()

        # Controls
        self.rate = Control(float)

        # States
        self.total = State(Energy, default=0)

        # Outputs
        self.value = Output(Energy)

    def forward(self, inlets):
        """Move no fluid."""
        outlets = dict()
        self.value = self.total
        return outlets

    def _advance_states(self, inlets, outlets, dt):
        return {"total": self.total + self.rate * dt}


def test_plain_call_uses_the_initial_state():
    """Outside a step a stateful module evaluates at its initial state."""
    tank = Tank()
    assert tank.stateful and not Line().stateful
    assert tank(fluid_in=STREAM).outlets.fluid_out.T == 300
    assert tank.initial_state() == {"temperature": 300}
    assert list(Line().states()) == ["first.temperature", "second.temperature"]
    assert "States:\n  temperature: K" in Tank.help()


def test_leaf_step_advances_its_state():
    """A leaf step starts from the given state and returns the end-of-step state."""
    tank = Tank()
    state, result = tank.step(None, 10, {"fluid_in": STREAM})
    assert result.outlets.fluid_out.T == 300
    assert state == {"temperature": pytest.approx(300 + 50 * 4217.4 * 10 / (4217.4 * 100))}
    state, result = tank.step(state, 10, {"fluid_in": STREAM})
    assert result.outlets.fluid_out.T == pytest.approx(305)


def test_composite_step_advances_every_descendant():
    """A composite steps its stateful children through its own forward, without a step method."""
    line = Line()
    assert line.initial_state() == {"first": {"temperature": 300}, "second": {"temperature": 300}}
    state, _ = line.step(None, 10, {"fluid_in": STREAM})
    state, result = line.step(state, 10, {"fluid_in": STREAM})
    assert state["first"]["temperature"] > state["second"]["temperature"] > 300
    assert result.outlets.fluid_out.T == 300
    first, second = 350 - 305, 305 - 300
    assert reading(result).duty == pytest.approx(STREAM.m_dot * 4217.4 * (first + second))


def test_state_errors():
    """Unknown states, assignments, wrong returns and double calls fail with the module path."""
    tank = Tank()
    with raises(
        gm.errors.ValidationError, "unknown_name", match="tank: unknown state 'temperatur'"
    ):
        tank.step({"temperatur": 300}, 10, {"fluid_in": STREAM})
    with pytest.raises(gm.errors.DefinitionError, match="changes only in _advance_states"):
        tank.temperature = 310
    with pytest.raises(gm.errors.ValidationError, match="tank.temperature: invalid state"):
        tank.step({"temperature": -1}, 10, {"fluid_in": STREAM})
    line = Line()
    line.second = line.first
    with raises(gm.errors.ValidationError, "invalid_design", match="more than once in one step"):
        line.step(None, 10, {"fluid_in": STREAM})


def test_advance_states_must_return_every_state():
    """An incomplete end-of-step mapping is a configuration error."""

    class Leaky(Tank):
        """Tank that forgets its state."""

        def _advance_states(self, inlets, outlets, dt):
            return {}

    with raises(gm.errors.ValidationError, "invalid_design", match="expected temperature"):
        Leaky().step(None, 10, {"fluid_in": STREAM})


def test_engine_replay_integrates_declared_states():
    """The engine steps a declared-state twin and keeps its state between ticks."""
    plant = Integrator()
    plant.bindings = {"": ModuleBindings(controls={"rate": Binding(column="rate", unit="-")})}
    frame = pd.DataFrame(
        {"rate": [1.0, 1.0, 1.0]},
        index=pd.date_range("2024-01-01", periods=3, freq="1s", tz="UTC"),
    )
    engine = gm.Engine(plant, on_error="raise")
    assert engine.replay(gm.Dataset.from_frame(frame))[""].value.tolist() == [0, 1, 2]
    assert engine.module_states[""] == {"total": 3}
