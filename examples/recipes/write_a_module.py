"""Write a small module of your own and use it in a plant.

Shows ``gm.modules.Module``, the declarations of ``gm.modules`` (``Parameter``, ``Inlet``,
``Output``, ``Outlet``) and ``gm.modules.check``. A class that states a ``category`` registers
itself.

Run with ``python examples/recipes/write_a_module.py``.
"""

import gemini as gm
from gemini.modules import Inlet, Outlet, Output, Parameter
from gemini.types import Pressure, PressureDifference, Stream

STREAM = gm.Stream(
    flow={"value": 40, "unit": "kg/s"},
    T={"value": 80, "unit": "degC"},
    p={"value": 6, "unit": "bar"},
)


class Orifice(gm.modules.Module):
    """A fixed restriction that takes a set pressure drop from the stream."""

    category = "piping"

    def __init__(self):
        """Declare the drop, one inlet, one outlet and the pressure it leaves at."""
        super().__init__()

        # Parameters
        self.pressure_drop = Parameter(PressureDifference)

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Outputs
        self.outlet_pressure = Output(Pressure)

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Lower the pressure of the stream."""

        # Outlets
        fluid_out = inlets.fluid_in.with_(p=inlets.fluid_in.p - self.pressure_drop)

        # Outputs
        self.outlet_pressure = fluid_out.p

        outlets = dict(fluid_out=fluid_out)
        return outlets


def main():
    """Check the class, call it alone and run it behind a filter in a plant."""
    example = {
        "parameters": {"pressure_drop": {"value": 1, "unit": "bar"}},
        "inlets": {"fluid_in": STREAM},
    }
    report = gm.modules.check(Orifice, example=example)
    print(f"Module checks passed: {report['passed']}")

    alone = Orifice().set_params("", {"pressure_drop": {"value": 1, "unit": "bar"}})(
        fluid_in=STREAM
    )
    print(f"Alone:                {alone.outputs.get('outlet_pressure', unit='bar'):.3f} bar")

    plant = gm.Plant("Throttled")
    plant.add("Filter", name="filter")
    plant.add("Orifice", name="orifice", params={"pressure_drop": {"value": 1, "unit": "bar"}})
    plant.connect("fluid_in", "filter.fluid_in")
    plant.connect("filter.fluid_out", "orifice.fluid_in")
    plant.connect("orifice.fluid_out", "fluid_out")
    outlet = plant(fluid_in=STREAM).outlets.fluid_out
    print(f"Behind a filter:      {gm.units.convert(outlet.p, 'Pa', 'bar'):.3f} bar")


if __name__ == "__main__":
    main()
