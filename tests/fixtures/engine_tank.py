"""A tank module, a valve and one-row datasets shared by the engine tests."""

import pandas as pd

import gemini as gm
from gemini.modules import Module
from gemini.modules.declarations import Control, Inlet, Outlet, Output, Parameter
from gemini.types import MassFlow, Pressure, Stream, Temperature
from gemini.types.bindings import Binding, ModuleBindings

TIME = pd.Timestamp("2024-01-01", tz="UTC")


class Tank(Module):
    """Leaf passing its inlet through; its mass-flow control may be bound volumetrically."""

    def __init__(self):
        """Declare a reference state, one stream and a mass-flow control."""
        super().__init__()

        # Parameters
        self.pressure = Parameter(Pressure)
        self.temperature = Parameter(Temperature)

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Controls
        self.m_dot = Control(MassFlow)

        # Outputs
        self.flow = Output(MassFlow)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Pass the inlet stream through."""

        # Outlets
        outlet = inlets.fluid_in

        outlets = dict(fluid_out=outlet)
        if self.m_dot < 0:
            raise ValueError("negative flow")
        self.flow = self.m_dot
        return outlets


class Valve(Module):
    """Leaf with a mass-flow control but no reference state."""

    def __init__(self):
        """Declare one control and one output."""
        super().__init__()

        # Controls
        self.m_dot = Control(MassFlow)

        # Outputs
        self.flow = Output(MassFlow)

    def forward(self, inlets):
        """Expose no fluid outlets."""

        outlets = dict()
        self.flow = self.m_dot
        return outlets


def tank(unit="kg/s"):
    """Return a configured tank bound to ``rate`` and inlet columns."""
    module = Tank()
    module.set_params(
        "", {"pressure": gm.units.Quantity(2e5, "Pa"), "temperature": gm.units.Quantity(320.0, "K")}
    )
    stream = {
        "m_dot": Binding(column="flow", unit="kg/s"),
        "p": Binding(column="p", unit="Pa"),
        "T": Binding(column="T", unit="K"),
    }
    module.bindings = {
        "": ModuleBindings(
            controls={"m_dot": Binding(column="rate", unit=unit)}, inlets={"fluid_in": stream}
        )
    }
    return module


def dataset(**columns):
    """Return a one-row dataset with the given column values."""
    return gm.Dataset.from_dict({k: [v] for k, v in columns.items()}, [TIME])


ROW = dict(rate=2.0, flow=10.0, p=3e5, T=330.0)
