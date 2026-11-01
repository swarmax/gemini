"""A small traceable leaf module shared by the graph tests."""

import numpy as np
import pytest

from gemini import ops
from gemini.errors import PhysicsError
from gemini.modules import Module
from gemini.modules.declarations import Boundary, Control, Inlet, Outlet, Output, Parameter, State
from gemini.modules.module import outputs_enabled
from gemini.ops import Constant
from gemini.types import BRINE, WATER, Electricity, Pressure, Ratio, Stream, Temperature
from gemini.units import Quantity

REFERENCE = Constant("REFERENCE", 2.0, "Pa", "pressure rise per unit gain and scale")


class Gain(Module):
    """Raise the inlet pressure by ``gain * scale * REFERENCE``; refuse a negative gain."""

    def __init__(self):
        """Declare one numeric and one text parameter, a control and two outputs."""
        super().__init__()

        # Parameters
        self.scale = Parameter(float)
        self.label = Parameter(str, default="x")

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Controls
        self.gain = Control(float)

        # Outputs
        self.rise = Output(float)
        self.boost = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Raise the pressure."""

        # Outlets
        inlet = inlets.fluid_in
        ops.check(
            self.gain >= 0,
            PhysicsError,
            "{path}: gain = {gain}",
            path=self.path,
            gain=self.gain,
        )
        outlet = inlet.with_(p=inlet.p + self.gain * self.scale * REFERENCE)

        outlets = dict(fluid_out=outlet)
        self.rise = outlets["fluid_out"].p - inlets.fluid_in.p
        self.boost = ops.where(self.rise > 0, ops.truediv(self.rise, self.gain), 0.0)
        return outlets


@pytest.fixture
def gain():
    """Return a configured ``Gain`` module."""
    return Gain().set_params("", {"scale": 3.0})


@pytest.fixture
def inlet():
    """Return a three-row inlet state."""
    return Stream(
        m_dot=Quantity(np.array([1.0, 1.0, 1.0]), "kg/s"),
        T=Quantity(np.array([300.0, 310.0, 320.0]), "K"),
        p=Quantity(np.array([1e5, 2e5, 3e5]), "Pa"),
        fluid=Gain().fluid,
    )


class Stepper(Module):
    """Raise the inlet pressure ``steps`` times by one pascal; ``steps`` is structural."""

    def __init__(self):
        """Declare a structural count, a numeric increment, an inlet and an outlet."""
        super().__init__()

        # Parameters
        self.steps = Parameter(int, default=2, structural=True)
        self.increment = Parameter(float, default=1.0)

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Add the increment once per step."""

        # Outlets
        pressure = inlets.fluid_in.p
        for _ in range(self.steps):
            pressure = pressure + self.increment
        return dict(fluid_out=inlets.fluid_in.with_(p=pressure))


@pytest.fixture
def stepper():
    """Return a configured ``Stepper`` module."""
    return Stepper()


class Source(Module):
    """Emit a stream of fixed state whose mass flow is the ``rate`` control; it has no inlet."""

    def __init__(self):
        """Declare a control, an output and an outlet."""
        super().__init__()

        # Controls
        self.rate = Control(float)

        # Outputs
        self.double = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Emit the stream."""

        # Outlets
        outlet = Stream(
            m_dot=Quantity(self.rate, "kg/s"),
            T=Quantity(300.0, "K"),
            p=Quantity(1e5, "Pa"),
            fluid=self.fluid,
        )
        outlets = dict(fluid_out=outlet)
        self.double = 2 * outlets["fluid_out"].m_dot
        return outlets


@pytest.fixture
def source():
    """Return a ``Source`` module."""
    return Source()


class Meter(Module):
    """Pass the stream on and draw ``draw * scale`` watts; a leaf with an output."""

    def __init__(self):
        """Declare a parameter, a control, an inlet, an output and an outlet."""
        super().__init__()

        # Parameters
        self.scale = Parameter(float, default=2.0)

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Controls
        self.draw = Control(float, ge=0)

        # Outputs
        self.electricity = Output(Electricity)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Pass the stream."""

        # Outlets
        outlets = dict(fluid_out=inlets.fluid_in)
        self.electricity = self.draw * self.scale
        return outlets


class Line(Module):
    """A meter, then a gain, then a second meter: a composite with every output formula."""

    def __init__(self):
        """Declare the children, the output formulas and the ports."""
        super().__init__()

        # Modules
        self.first = Meter()
        self.gain = Gain().set_params("", {"scale": 3.0})
        self.second = Meter()

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Controls
        self.boost = Control(float, default=1.0)

        # Outputs
        self.rise = Output(float)
        self.pressure = Output(float)
        self.electricity = Output(float)
        self.efficiency = Output(float | None)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Connect the children in series; the second meter draws the line's own control."""

        # Modules
        metered = self.first(fluid_in=inlets.fluid_in, draw=1.0)
        raised = self.gain(fluid_in=metered.outlets.fluid_out, gain=self.boost)
        metered_again = self.second(fluid_in=raised.outlets.fluid_out)

        # Outputs
        if outputs_enabled():
            self.rise = raised.outputs.rise
            self.pressure = raised.outlets.fluid_out.p
            self.electricity = metered_again.outputs.electricity
            self.efficiency = ops.where(
                ops.eq(self.electricity, 0), None, ops.truediv(self.rise, self.electricity)
            )

        # Outlets
        outlets = dict(fluid_out=metered_again.outlets.fluid_out)
        return outlets


@pytest.fixture
def line():
    """Return a ``Line`` composite with its second meter drawing 2 W."""
    line = Line()
    line.second.draw = 2.0
    return line


class Tank(Module):
    """Pass the stream on and carry a level that rises by the inlet mass flow each step."""

    def __init__(self):
        """Declare a state, an inlet, an output and an outlet."""
        super().__init__()

        # States
        self.level = State(float, default=0.0)

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Outputs
        self.content = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Pass the stream."""

        # Outlets
        outlets = dict(fluid_out=inlets.fluid_in)
        self.content = self.level + inlets.fluid_in.m_dot
        return outlets

    def _advance_states(self, inlets, outlets, dt):
        return dict(level=self.content)


class Twice(Module):
    """Call one gain twice on the same inlet and add the two pressures."""

    def __init__(self):
        """Declare the child, an inlet and an outlet."""
        super().__init__()

        # Modules
        self.gain = Gain().set_params("", {"scale": 3.0})

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Call the child twice; both calls share its inputs."""

        # Modules
        first = self.gain(fluid_in=inlets.fluid_in)
        second = self.gain(fluid_in=inlets.fluid_in)

        # Outlets
        outlet = inlets.fluid_in.with_(p=first.outlets.fluid_out.p + second.outlets.fluid_out.p)
        outlets = dict(fluid_out=outlet)
        return outlets


@pytest.fixture
def twice():
    """Return a ``Twice`` composite."""
    return Twice()


@pytest.fixture
def tank():
    """Return a stateful ``Tank`` module."""
    return Tank()


class Chain(Module):
    """Meter, then the ``middle`` module, then a meter: the middle one can be a graph break."""

    def __init__(self, middle):
        """Declare the children, the output formulas, the drive control and the ports."""
        super().__init__()

        # Modules
        self.first = Meter()
        self.middle = middle
        self.last = Meter()

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Controls
        self.drive = Control(float, default=1.0)

        # Outputs
        self.value = Output(float)
        self.pressure = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Connect the children in series; every control of the middle module gets ``drive``."""

        # Modules
        metered = self.first(fluid_in=inlets.fluid_in, draw=1.0)
        controls = {name: self.drive for name in self.middle._controls}
        through = self.middle(fluid_in=metered.outlets.fluid_out, **controls)
        last = self.last(fluid_in=through.outlets.fluid_out, draw=1.0)

        # Outputs
        self.value = through.outputs[next(iter(self.middle._outputs))]
        self.pressure = last.outlets.fluid_out.p

        # Outlets
        outlets = dict(fluid_out=last.outlets.fluid_out)
        return outlets


class Stubborn(Gain):
    """A gain whose forward needs a number from the inlet: it cannot be traced."""

    def forward(self, inlets):
        """Raise the pressure by the gain times the inlet temperature as a plain float."""

        # Outlets
        ops.check(
            self.gain >= 0,
            PhysicsError,
            "{path}: gain = {gain}",
            path=self.path,
            gain=self.gain,
        )
        outlet = inlets.fluid_in.with_(p=inlets.fluid_in.p + self.gain * float(inlets.fluid_in.T))
        outlets = dict(fluid_out=outlet)
        self.rise = outlets["fluid_out"].p - inlets.fluid_in.p
        self.boost = 0.0
        return outlets


class Opaque(Module):
    """A composite whose own forward needs a number from the inlet: it cannot be traced."""

    def __init__(self):
        """Declare one child, an inlet, an output to copy and an outlet."""
        super().__init__()

        # Modules
        self.meter = Meter()

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Outputs
        self.electricity = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Refuse a traced value."""

        # Modules
        metered = self.meter(fluid_in=inlets.fluid_in, draw=float(inlets.fluid_in.T))

        # Outputs
        self.electricity = metered.outputs.electricity

        # Outlets
        outlets = dict(fluid_out=metered.outlets.fluid_out)
        return outlets


class Switcher(Module):
    """Pass the stream on, but with water when the inlet is warmer than 305 K."""

    def __init__(self):
        """Declare an inlet, an output and an outlet."""
        super().__init__()

        # States
        self.level = State(float, default=0.0)

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Outputs
        self.seen = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Pass the stream; the fluid depends on the value of a row."""

        # Outlets
        fluid = WATER if inlets.fluid_in.T < 305.0 else BRINE
        outlets = dict(
            fluid_out=Stream(
                m_dot=Quantity(inlets.fluid_in.m_dot, "kg/s"),
                T=Quantity(inlets.fluid_in.T, "K"),
                p=Quantity(inlets.fluid_in.p, "Pa"),
                fluid=fluid,
            )
        )
        self.seen = inlets.fluid_in.T
        return outlets

    def _advance_states(self, inlets, outlets, dt):
        return dict(level=self.seen)


class Vectored(Module):
    """Pass the stream on and report the inlet pressure and one pascal more as a list."""

    def __init__(self):
        """Declare an inlet, a list output and an outlet."""
        super().__init__()

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Outputs
        self.profile = Output(list[float])

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Pass the stream."""

        # Outlets
        outlets = dict(fluid_out=inlets.fluid_in)
        self.profile = [inlets.fluid_in.p, inlets.fluid_in.p + 1.0]
        return outlets


class Bounded(Module):
    """Declare a bound on a control, a boundary and three outputs: a pressure, a list, a ratio."""

    def __init__(self):
        """Declare the bounded values and the passing stream."""
        super().__init__()

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Controls
        self.setpoint = Control(Pressure)

        # Boundaries
        self.ambient = Boundary(Temperature)

        # Outputs
        self.margin = Output(Pressure)
        self.profile = Output(list[Pressure])
        self.share = Output(Ratio | None)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Pass the stream."""

        # Outlets
        outlets = dict(fluid_out=inlets.fluid_in)
        self.margin = inlets.fluid_in.p - self.setpoint
        self.profile = [self.setpoint, self.setpoint - 1.0]
        self.share = ops.where(self.ambient > 1000.0, None, self.setpoint / inlets.fluid_in.p)
        return outlets


@pytest.fixture
def bounded():
    """Return a ``Bounded`` module."""
    return Bounded()


class Optional(Module):
    """Report ``-1`` while its optional control has no value, else the control doubled."""

    def __init__(self):
        """Declare an optional control, an output and no streams."""
        super().__init__()

        # Controls
        self.rate = Control(float | None, default=None)

        # Outputs
        self.double = Output(float)

    def forward(self, inlets):
        """Expose no fluid outlets."""

        outlets = dict()
        self.double = ops.where(ops.isnan(self.rate), -1.0, 2 * self.rate)
        return outlets


@pytest.fixture
def optional():
    """Return an ``Optional`` module."""
    return Optional()
