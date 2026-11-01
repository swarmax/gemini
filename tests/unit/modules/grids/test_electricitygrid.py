"""Grid import/export netting, connection limits and use inside a plant."""

import pytest

from gemini.modules import Module, collect_flows, energy_balance
from gemini.modules.declarations import Control, Inlet, Outlet, Output
from gemini.modules.grids import ElectricityGrid
from gemini.modules.heating import ElectricBoiler
from gemini.modules.power import ORC
from gemini.types import Power, Stream
from gemini.units import Quantity
from tests.fixtures import si
from tests.fixtures.air import air
from tests.fixtures.equivalence import assert_module_matches
from tests.fixtures.reading import reading


def grid(**changes):
    """Return a connection with ``changes``."""
    return si.set_params(ElectricityGrid(), "", changes)


def test_import_and_export_within_unlimited_connection():
    """Net consumption is imported; surplus is exported."""
    out = reading(grid()(power_out=[2e6, 1e6], power_in=[1e6]))
    assert out.net_import == 2e6 and out.net_export == 0
    assert not out.is_import_limited and out.unserved_consumption == 0
    out = reading(grid()(power_out=[1e6], power_in=[4e6]))
    assert out.net_export == 3e6 and out.net_import == 0


def test_connection_limits():
    """Imports above the limit go unserved; exports above it are curtailed."""
    connection = grid(
        import_limit={"value": 1, "unit": "MW"}, export_limit={"value": 0.5, "unit": "MW"}
    )
    out = reading(connection(power_out=[3e6], power_in=[1e6]))
    assert out.net_import == 1e6 and out.unserved_consumption == 1e6 and out.is_import_limited
    out = reading(connection(power_out=[], power_in=[2e6]))
    assert out.net_export == 5e5 and out.curtailed_generation == 1.5e6 and out.is_export_limited
    out = reading(grid(export_limit=0)())
    assert out.net_export == 0 and not out.is_export_limited


class GridPlant(Module):
    """An ORC selling to the grid while an electric boiler buys from it."""

    def __init__(self):
        """Declare the test plant."""
        super().__init__()

        # Modules
        self.orc = ORC().set_params(
            "",
            {
                "minimum_brine_outlet_temperature": Quantity(343.15, "K"),
                "pinch": Quantity(5, "K"),
                "carnot_fraction": 0.5,
                "condenser_approach": Quantity(15, "K"),
                "parasitic_fraction": 0.15,
                "capacity": Quantity(5e6, "W"),
            },
        )
        self.boiler = ElectricBoiler().set_params(
            "", {"capacity": Quantity(1e6, "W"), "efficiency": 0.99}
        )
        self.grid = grid(export_limit={"value": 10, "unit": "MW"})

        # Inlets
        self.fluid_in = Inlet(Stream)
        self.water_in = Inlet(Stream)

        # Outputs
        self.net_export = Output(float)

        # Outlets
        self.fluid_out = Outlet(Stream)
        self.water_out = Outlet(Stream)

    def forward(self, inlets):
        """Generate, consume, then settle with the grid."""

        # Modules
        generated = self.orc(fluid_in=inlets.fluid_in, air_in=air(288.15))
        heated = self.boiler(fluid_in=inlets.water_in, temperature_setpoint=353.15)
        settled = self.grid(
            power_out=[heated.inlets.power_in], power_in=[generated.outlets.power_out]
        )

        # Outputs
        self.net_export = settled.outputs.net_export

        # Outlets
        fluid_out = generated.outlets.fluid_out
        water_out = heated.outlets.fluid_out

        outlets = dict(fluid_out=fluid_out, water_out=water_out)
        return outlets


def test_grid_is_not_counted_in_the_energy_audit():
    """Plant totals keep the ORC and boiler energy once; the grid adds none."""
    plant = GridPlant()
    result = plant(
        fluid_in=Stream(
            m_dot=Quantity(100, "kg/s"), T=Quantity(423.15, "K"), p=Quantity(10e5, "Pa")
        ),
        water_in=Stream(m_dot=Quantity(5, "kg/s"), T=Quantity(313.15, "K"), p=Quantity(3e5, "Pa")),
    )
    orc, boiler = reading(result.children["orc"]), reading(result.children["boiler"])
    flows = collect_flows(result)
    assert flows["electricity_generated"] == orc.electricity_generated
    assert flows["electricity"] == boiler.electricity
    assert result.outputs.net_export == pytest.approx(
        orc.electricity_generated - boiler.electricity, rel=1e-12
    )
    assert energy_balance(plant, result)["relative_residual"] < 1e-12


class Connected(Module):
    """A connection whose both sides are controls, for a run over rows."""

    def __init__(self):
        """Declare the connection and the row-carrying inlet."""
        super().__init__()

        # Modules
        self.grid = grid(import_limit={"value": 2, "unit": "MW"})

        # Inlets
        self.rows = Inlet(Stream)

        # Controls
        self.consumption = Control(Power)
        self.generation = Control(Power)

        # Outputs
        self.net_import = Output(float)
        self.net_export = Output(float)

    def forward(self, inlets):
        """Settle one row."""

        # Modules
        settled = self.grid(power_out=[self.consumption], power_in=[self.generation])

        # Outputs
        self.net_import = settled.outputs.net_import
        self.net_export = settled.outputs.net_export

        outlets = dict()
        return outlets


def test_traced_call_matches_one_call_per_row():
    """Import, export, limited and unlimited rows trace and equal one call per row."""
    rows = [
        dict(
            rows=Stream(m_dot=Quantity(1.0, "kg/s"), T=Quantity(300.0, "K"), p=Quantity(1e5, "Pa")),
            consumption=consumption,
            generation=generation,
        )
        for consumption, generation in [(3e6, 1e6), (1e6, 4e6), (0.0, 2e6), (5e5, 5e5), (4e6, 0.0)]
    ]
    assert_module_matches(Connected(), rows)
