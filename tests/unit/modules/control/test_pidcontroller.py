"""Discrete PID controller: start-of-step command, integral, derivative and anti-windup."""

from types import SimpleNamespace

import numpy as np
import pytest

import gemini as gm
from gemini.modules import Module
from gemini.modules.control import PIDController
from gemini.modules.declarations import Boundary, Control, Inlet, Outlet, Output
from gemini.modules.storage import ThermalStorage
from gemini.types import Stream, Temperature
from tests.fixtures import si
from tests.fixtures.air import air
from tests.fixtures.designs import with_values
from tests.fixtures.equivalence import assert_close
from tests.fixtures.errors import raises


def _controller(**changes):
    """Return a reverse-acting PID controller with K = 2, Ti = 100 s and a 0..1 command."""
    params = dict(
        proportional_gain=2.0,
        integral_time=100.0,
        minimum_output=0.0,
        maximum_output=1.0,
        direction="reverse",
    )
    return si.set_params(PIDController(), "", params | changes)


def _step(pid, state, dt, measurement):
    """Step the controller (which has no inlets) at a persisted measurement."""
    pid.measurement = measurement
    return pid.step(state, dt, {})


def test_plain_call_is_proportional_and_clamped():
    """Outside a step the initial states give K e, clamped to the output limits."""
    pid = _controller()
    out = pid(setpoint=1.0, measurement=0.8).outputs
    assert out.error == pytest.approx(0.2) and out.command == pytest.approx(0.4)
    assert not out.is_saturated
    out = pid(setpoint=1.0, measurement=0.0).outputs
    assert out.command == 1.0 and out.is_saturated
    direct = _controller(direction="direct")
    out = direct(setpoint=1.0, measurement=1.2).outputs
    assert out.error == pytest.approx(0.2) and out.command == pytest.approx(0.4)
    assert direct(setpoint=1.0, measurement=0.9).outputs.command == 0


def test_steps_integrate_and_differentiate_with_start_of_step_states():
    """I lags one step (explicit sum) and D is the backward difference over the last step."""
    pid = _controller(derivative_time=20.0)
    pid.setpoint = 1.0
    state, result = _step(pid, None, 10, 0.9)
    assert result.outputs.command == pytest.approx(2 * 0.1)
    assert state == {
        "integral": pytest.approx(2 * 10 / 100 * 0.1),
        "previous_error": pytest.approx(0.1),
        "previous_step": 10,
    }
    state, result = _step(pid, state, 10, 0.85)
    integral = 2 * 10 / 100 * 0.1
    derivative = 2 * 20 * (0.15 - 0.1) / 10
    assert result.outputs.command == pytest.approx(2 * 0.15 + integral + derivative)
    assert state["integral"] == pytest.approx(integral + 2 * 10 / 100 * 0.15)


def test_clamping_stops_windup_and_allows_unwinding():
    """A saturated command does not integrate further out, but integrates back in."""
    pid = _controller()
    pid.setpoint = 1.0
    state = {"integral": 0.9, "previous_error": None, "previous_step": None}
    held, result = _step(pid, state, 60, 0.5)
    assert result.outputs.is_saturated and held["integral"] == 0.9
    unwound, result = _step(pid, held, 60, 1.1)
    assert result.outputs.command == pytest.approx(0.9 - 0.2)
    assert unwound["integral"] == pytest.approx(0.9 - 2 * 60 / 100 * 0.1)
    proportional = _controller(integral_time=None)
    proportional.setpoint = 1.0
    assert _step(proportional, None, 60, 0.9)[0]["integral"] == 0


def test_invalid_settings_raise():
    """Crossed output limits and nonpositive tuning are configuration errors."""
    with raises(
        gm.errors.ValidationError,
        "invalid_design",
        match="expected minimum_output < maximum_output",
    ):
        _controller(minimum_output=1.0, maximum_output=0.0)(setpoint=1, measurement=0)
    with pytest.raises(gm.errors.ValidationError):
        _controller(proportional_gain=0)
    with pytest.raises(gm.errors.ValidationError):
        _controller(integral_time=0)
    with raises(gm.errors.ValidationError, "missing_value"):
        _controller()(setpoint=1)


class ControlledTank(Module):
    """Storage tank whose charge flow a PID controller throttles on a measured temperature."""

    def __init__(self):
        """Declare the test composite."""
        super().__init__()

        # Modules
        self.controller = _controller(proportional_gain=0.1, integral_time=600.0)
        self.storage = with_values(ThermalStorage()).set_params(
            "",
            {
                "service": "hot",
                "volume": gm.units.Quantity(1.0, "m3"),
                "heat_loss_conductance": gm.units.Quantity(0, "W/K"),
                "reference_temperature": gm.units.Quantity(313.15, "K"),
            },
        )

        # Inlets
        self.charge_in = Inlet(Stream)
        self.discharge_in = Inlet(Stream)

        # Controls
        self.temperature_setpoint = Control(Temperature)

        # Boundaries
        self.measured_temperature = Boundary(Temperature)

        # Outputs
        self.command = Output(float)

        # Outlets
        self.charge_out = Outlet(Stream)
        self.discharge_out = Outlet(Stream)

    def forward(self, inlets):
        """Throttle the charge flow by the controller command, then pass the tank."""

        # Modules
        control = self.controller(
            measurement=self.measured_temperature, setpoint=self.temperature_setpoint
        )
        charge_in = inlets.charge_in
        throttled = charge_in.with_(m_dot=charge_in.m_dot * control.outputs.command)
        self.command = control.outputs.command
        stored = self.storage(
            charge_in=throttled, discharge_in=inlets.discharge_in, air_in=air(293.15)
        )

        # Outlets
        charge_out = stored.outlets.charge_out
        discharge_out = stored.outlets.discharge_out

        outlets = dict(charge_out=charge_out, discharge_out=discharge_out)
        return outlets


def test_controller_steps_inside_a_composite():
    """The parent passes measurement= and uses the command; both children advance per step."""
    plant = ControlledTank()._set_inputs(
        {"temperature_setpoint": 343.15, "measured_temperature": 333.15}
    )
    streams = {
        "charge_in": Stream(
            m_dot=gm.units.Quantity(1.0, "kg/s"),
            T=gm.units.Quantity(353.15, "K"),
            p=gm.units.Quantity(3e5, "Pa"),
        ),
        "discharge_in": Stream(
            m_dot=gm.units.Quantity(0.0, "kg/s"),
            T=gm.units.Quantity(313.15, "K"),
            p=gm.units.Quantity(3e5, "Pa"),
        ),
    }
    state, result = plant.step(None, 60, streams)
    assert result.outputs.command == pytest.approx(0.1 * 10)
    assert result.children["storage"].inlets.charge_in.m_dot == pytest.approx(1.0)
    assert state["controller"]["integral"] == 0
    plant.measured_temperature = 338.15
    state, result = plant.step(state, 60, streams)
    assert result.outputs.command == pytest.approx(0.1 * 5)
    assert state["controller"]["integral"] == pytest.approx(0.1 * 60 / 600 * 5)
    assert state["storage"]["temperature"] > 293.15


PID_ROWS = [
    (0.5, 1.0, 0.9, 0.2, 60),
    (0.9, 1.0, 0.5, 0.2, 60),
    (0.1, 0.0, 0.5, 0.2, 60),
    (0.5, 1.0, 0.5, 0.0, 30),
]
"""Rows of integral, setpoint, measurement, previous error and previous step [s]."""


@pytest.mark.parametrize("direction", ["reverse", "direct"])
@pytest.mark.parametrize("integral_time", [100.0, None])
def test_pid_command_and_advance_match_per_row(monkeypatch, direction, integral_time):
    """The command, the anti-windup integral and the stored error on stacked rows equal per row."""
    pid = _controller(
        direction=direction, integral_time=integral_time, derivative_time=5.0, maximum_output=1.2
    )

    def load(*columns):
        for name, column in zip(
            ("integral", "setpoint", "measurement", "previous_error", "previous_step"), columns
        ):
            monkeypatch.setattr(PIDController, name, column, raising=False)

    def advance(*columns):
        load(*columns)
        return pid._advance_states(SimpleNamespace(), None, 60)

    def command(*columns):
        load(*columns)
        return pid._unclamped_command()

    stacked = [np.array(column) for column in zip(*PID_ROWS)]
    assert_close(command(*stacked), [command(*row) for row in PID_ROWS], "unclamped command")
    expected = [advance(*row) for row in PID_ROWS]
    actual = advance(*stacked)
    for name in ("integral", "previous_error"):
        assert_close(actual[name], [e[name] for e in expected], name)
    assert actual["previous_step"] == 60
