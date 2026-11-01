"""Build plants from modules, validate them and fix an unconnected port.

A leaf module computes and a plant connects. A plant class declares its children, ports and
connections and never writes ``forward``; ``gm.Plant`` builds the same with ``add`` and ``connect``.
Shows a ``gm.Plant`` subclass, ``gm.Plant``, ``add``, ``connect``, ``validate`` and
``summary``. A plant that buys what it needs from the grids has no plant ports; a building block
for other plants names its ports.

Run with ``python examples/basics/03_build_a_plant.py``.
"""

import gemini as gm
from gemini.modules import Inlet, Outlet, Output
from gemini.types import Stream

FILTERS = 2


class FilterTrain(gm.Plant):
    """Two filters in series, a plant class: it connects and never writes ``forward``."""

    def __init__(self):
        """Declare the children, the ports, the connections and one output."""
        super().__init__()

        # Modules
        self.first = gm.modules.Filter()
        self.second = gm.modules.Filter()

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Outlets
        self.fluid_out = Outlet(Stream)

        # Connections
        self.connect("fluid_in", "first.fluid_in")
        self.connect("first.fluid_out", "second.fluid_in")
        self.connect("second.fluid_out", "fluid_out")

        # Outputs
        self.pressure_loss = Output.difference("first.fluid_in.p", "second.fluid_out.p")


def treatment_train():
    """Return a building block of filters in series, with its two ports named."""
    plant = gm.Plant("TreatmentTrain")
    for index in range(FILTERS):
        plant.add("Filter", f"filter_{index}")
    for index in range(FILTERS - 1):
        plant.connect(f"filter_{index}", f"filter_{index + 1}")
    plant.connect("fluid_in", "filter_0.fluid_in")
    plant.connect(f"filter_{FILTERS - 1}.fluid_out", "fluid_out")
    return plant


def boiler_plant():
    """Return a boiler that heats a heating grid, with its heat loss still unconnected."""
    plant = gm.Plant("BoilerPlant")
    plant.add(
        "HeatingGrid",
        name="users",
        params={
            "return_temperature": {"value": 60, "unit": "degC"},
            "return_pressure": {"value": 6, "unit": "bar"},
        },
    )
    plant.add(
        "Boiler", name="boiler", params={"capacity": {"value": 1, "unit": "MW"}, "efficiency": 0.9}
    )
    plant.add("GasGrid", name="gas")
    plant.add("Atmosphere", name="air")
    plant.connect("users.return_out", "boiler.fluid_in")
    plant.connect("boiler.fluid_out", "users.supply_in")
    plant.connect("gas.gas_out", "boiler.fuel_in")
    plant.connect("boiler.flue_out", "air.gas_in")
    return plant


def main():
    """Call the building block, then find and fix the missing connection of the boiler plant."""
    train = treatment_train()
    result = train(
        fluid_in=gm.Stream(
            flow={"value": 10, "unit": "kg/s"},
            T={"value": 60, "unit": "degC"},
            p={"value": 10, "unit": "bar"},
        )
    )
    outlet = result.outlets.fluid_out
    print(f"After {FILTERS} filters:     {gm.units.convert(outlet.p, 'Pa', 'bar'):.4f} bar")

    outputs = FilterTrain()(
        fluid_in=gm.Stream(
            flow={"value": 10, "unit": "kg/s"},
            T={"value": 60, "unit": "degC"},
            p={"value": 10, "unit": "bar"},
        )
    ).outputs
    print(f"Plant class loss:    {gm.units.convert(outputs.pressure_loss, 'Pa', 'bar'):.4f} bar")

    plant = boiler_plant()
    for problem in plant.validate(on_error="record"):
        print(f"Problem:             {problem['code']} at {problem['path']}")
    plant.connect("boiler.loss_out", "air.heat_in")
    print(f"After the fix:       {len(plant.validate(on_error='record'))} problems")
    print(plant.summary())


if __name__ == "__main__":
    main()
