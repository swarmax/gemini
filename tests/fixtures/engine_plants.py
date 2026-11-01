"""Synthetic modules and plants of the engine tests: boosters, a reservoir, a pair and a holder.

``Booster`` is a stateless leaf with a health, ``Reservoir`` a stateful one, ``Pair`` two boosters
(and a reservoir) bound as twins, ``Duo`` a composite and ``Holder`` a plant whose twin is a
``Duo``. ``pair_frame`` is the measured data they read.
"""

import numpy as np
import pandas as pd

from gemini import ops
from gemini.errors import PhysicsError
from gemini.modules import Module
from gemini.modules.declarations import Control, Inlet, Outlet, Output, Parameter, State
from gemini.plants.plant import Plant
from gemini.types import Electricity, Health, Ratio, Stream
from gemini.types.bindings import Binding, DatedParams, ModuleBindings

TICKS = pd.date_range("2024-01-01", periods=12, freq="15min", tz="UTC")


class Booster(Module):
    """Raise the pressure by ``level * gain``; refuse a negative level; report a health."""

    def __init__(self):
        """Declare a parameter, an inlet, a control, outputs and an outlet."""
        super().__init__()

        # Parameters
        self.gain = Parameter(float, default=2.0)

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Controls
        self.level = Control(float)

        # Outputs
        self.rise = Output(float)
        self.power = Output(Electricity)
        self.share = Output(Ratio | None, soft_sensor=True)
        self.inverse = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Raise the pressure."""

        # Outlets
        ops.check(
            self.level >= 0,
            PhysicsError,
            "{path}: level = {level}",
            path=self.path,
            level=self.level,
        )
        outlet = inlets.fluid_in.with_(p=inlets.fluid_in.p + self.level * self.gain)
        outlets = dict(fluid_out=outlet)
        self.rise = outlets["fluid_out"].p - inlets.fluid_in.p
        self.power = self.rise * inlets.fluid_in.m_dot
        self.share = ops.where(self.level == 0, None, self.rise / ops.maximum(self.level, 1e-9))
        self.inverse = ops.truediv(1.0, self.level)
        return outlets

    def health(self, result, measured):
        """Compare the rise with the measured one."""
        error = abs(result.outputs.rise - measured["rise"])
        return Health(score=1 / (1 + error / 100), alarm=error > 5e4, message="rise")


class Reservoir(Module):
    """A stateful leaf: it carries the sum of the flows it saw."""

    def __init__(self):
        """Declare a state, an inlet, an output and an outlet."""
        super().__init__()

        # States
        self.total = State(float, default=0.0)

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
        self.content = self.total + inlets.fluid_in.m_dot
        return outlets

    def _advance_states(self, inlets, outlets, dt):
        return dict(total=self.content)


class Pair(Module):
    """Two boosters side by side, each a twin; the root is only a container."""

    def __init__(self):
        """Declare the children and the bindings of both twins."""
        super().__init__()

        # Modules
        self.first = Booster()
        self.second = Booster()
        self.tank = Reservoir()


def inlet_bindings():
    """Return the bindings of an inlet stream: volumetric flow, Celsius and bar."""
    return {
        "m_dot": Binding(column="flow", unit="m3/h"),
        "T": Binding(column="temperature", unit="°C"),
        "p": Binding(column="pressure", unit="bar"),
    }


def pair_bindings(path_prefix=""):
    """Return the bindings of both twins of a pair below ``path_prefix``."""
    return {
        f"{path_prefix}first": ModuleBindings(
            controls={"level": Binding(column="level", unit="bar")},
            inlets={"fluid_in": inlet_bindings()},
            measured={"rise": Binding(column="rise", unit="bar")},
        ),
        f"{path_prefix}second": ModuleBindings(
            controls={"level": Binding(column="level2", unit="Pa")},
            inlets={"fluid_in": inlet_bindings()},
            measured={"rise": Binding(column="rise", unit="bar")},
        ),
    }


def pair_plant(with_tank=False):
    """Return a pair, with a reservoir twin when ``with_tank``."""
    plant = Pair()
    plant.bindings = pair_bindings()
    if with_tank:
        plant.bindings["tank"] = ModuleBindings(inlets={"fluid_in": inlet_bindings()})
    return plant


def dated_pair_plant():
    """Return a pair whose gain changes from 2 to 5 at the seventh tick."""
    plant = pair_plant()
    for module in (plant.first, plant.second):
        module._param_history = [
            DatedParams(params={"gain": 2.0}),
            DatedParams(valid_from=TICKS[6], params={"gain": 5.0}),
        ]
    return plant


def pair_frame(changes=None):
    """Return the 12 ticks of measured data, with ``changes`` a map of (column, row) to a value."""
    rows = len(TICKS)
    frame = pd.DataFrame(
        {
            "flow": np.linspace(10.0, 20.0, rows),
            "temperature": np.linspace(60.0, 70.0, rows),
            "pressure": np.linspace(5.0, 6.0, rows),
            "level": np.linspace(0.1, 1.3, rows),
            "level2": np.linspace(1e4, 3e5, rows),
            "rise": np.linspace(0.1, 1.3, rows),
        },
        index=TICKS,
    )
    for (column, row), value in (changes or {}).items():
        frame[column] = frame[column].astype(object if isinstance(value, str) else float)
        frame.loc[TICKS[row], column] = value
    return frame


class Duo(Module):
    """Two boosters in series: a composite twin with a formula output and an automatic sum."""

    def __init__(self):
        """Declare the children, the inlet, the outputs and the outlet."""
        super().__init__()

        # Modules
        self.front = Booster()
        self.back = Booster()

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Controls
        self.level = Control(float)

        # Outputs
        self.rise = Output(float)
        self.power = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Both boosters get the duo's level."""

        # Modules
        first = self.front(fluid_in=inlets.fluid_in, level=self.level)
        second = self.back(fluid_in=first.outlets.fluid_out, level=self.level)

        # Outputs
        self.rise = second.outputs.rise
        self.power = second.outputs.power

        # Outlets
        outlets = dict(fluid_out=second.outlets.fluid_out)
        return outlets


class Holder(Module):
    """A container whose child ``duo`` is a composite twin."""

    def __init__(self):
        """Declare the child."""
        super().__init__()

        # Modules
        self.duo = Duo()


def holder_plant(nested=False):
    """Return a holder; ``nested`` binds the first booster of the duo as a twin below it."""
    plant = Holder()
    plant.bindings = {
        "duo": ModuleBindings(
            controls={"level": Binding(column="level", unit="bar")},
            inlets={"fluid_in": inlet_bindings()},
        )
    }
    if nested:
        plant.bindings["duo.front"] = ModuleBindings(
            controls={"level": Binding(column="level", unit="bar")},
            inlets={"fluid_in": inlet_bindings()},
            measured={"rise": Binding(column="rise", unit="bar")},
        )
    return plant


class Warmer(Module):
    """Move the temperature half way to a control and set the flow; the first guess is 300 K."""

    def __init__(self):
        """Declare a control, an inlet, an output and an outlet."""
        super().__init__()

        # Controls
        self.target = Control(float)

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Outputs
        self.drop = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Return the warmed stream, flowing at 2 kg/s, and the change of temperature."""

        # Outlets
        outlet = inlets.fluid_in.with_(T=0.5 * inlets.fluid_in.T + 0.5 * self.target, m_dot=2.0)
        self.drop = inlets.fluid_in.T - outlet.T
        return dict(fluid_out=outlet)

    def _loop_start(self, port, entering):
        return 300.0


class Carrier(Module):
    """Pass the stream on at 2 bar."""

    def __init__(self):
        """Declare an inlet and an outlet."""
        super().__init__()

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Return the stream at 2 bar."""
        return dict(fluid_out=inlets.fluid_in.with_(p=2e5))


class Ring(Plant):
    """A warmer and a carrier in a closed loop, with no inlet."""

    def __init__(self):
        """Connect the two modules in a ring."""
        super().__init__()

        # Modules
        self.warmer = Warmer()
        self.carrier = Carrier()

        # Connections
        self.connect("warmer.fluid_out", "carrier.fluid_in")
        self.connect("carrier.fluid_out", "warmer.fluid_in")


def loop_plant():
    """Return a ring: a plant that closes one loop."""
    return Ring()
