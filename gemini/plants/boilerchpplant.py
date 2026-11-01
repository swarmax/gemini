"""Nodal doublet with a heat exchanger, a boiler and a CHP on the secondary network."""

from gemini.modules.declarations import Inlet, Outlet
from gemini.modules.environment import Atmosphere
from gemini.modules.exchangers import HeatExchanger
from gemini.modules.grids import ElectricityGrid, GasGrid
from gemini.modules.heating import CHP, Boiler
from gemini.modules.piping import Mixer, Splitter
from gemini.modules.treatment import Degasser, Filter
from gemini.plants.nodaldoublet import NodalDoublet
from gemini.plants.plant import Plant
from gemini.types import Stream


class BoilerChpPlant(Plant):
    """Nodal doublet, surface treatment, exchanger, and a boiler and CHP on the secondary.

    The port of the upstream GEMINI simulator's ``doublet_plant`` example. The producer is solved
    for its rate at the ``doublet.wellhead_pressure`` boundary, the brine passes a degasser, a
    filter, the heat exchanger and a second filter, and the injector is solved for the pump head
    it needs. The secondary water is split in two: one part is heated by the exchanger and topped
    up by a gas boiler, the other is heated by a gas-engine CHP, and both are mixed again.
    ``inputs/plants/BoilerChpPlant.json`` carries the well, reservoir and ESP data of the
    upstream example.

    Not schedulable: its doublet is a ``NodalDoublet``, solved for its wellhead pressure, and a run
    sets its setpoints.
    """

    def __init__(self):
        """Build the plant in flow order."""
        super().__init__()

        # Modules
        self.doublet = NodalDoublet()
        self.degasser = Degasser()
        self.hot_filter = Filter()
        self.heat_exchanger = HeatExchanger()
        self.cold_filter = Filter()
        self.splitter = Splitter()
        self.boiler_gas = GasGrid()
        self.chp_gas = GasGrid()
        self.boiler = Boiler()
        self.chp = CHP()
        self.mixer = Mixer()
        self.electricity_grid = ElectricityGrid()
        self.air = Atmosphere()

        # Inlets
        self.return_in = Inlet(Stream)

        # Outlets
        self.supply_out = Outlet(Stream)

        # Connections
        self.connect("return_in", "splitter.fluid_in")
        self.connect("doublet.supply_out", "degasser.fluid_in")
        self.connect("degasser.liquid_out", "hot_filter.fluid_in")
        self.connect("hot_filter.fluid_out", "heat_exchanger.hot_in")
        self.connect("splitter.branch1_out", "heat_exchanger.cold_in")
        self.connect("heat_exchanger.hot_out", "cold_filter.fluid_in")
        self.connect("cold_filter.fluid_out", "doublet.return_in")
        self.connect("heat_exchanger.cold_out", "boiler.fluid_in")
        self.connect("boiler_gas.gas_out", "boiler.fuel_in")
        self.connect("splitter.branch2_out", "chp.fluid_in")
        self.connect("chp_gas.gas_out", "chp.fuel_in")
        self.connect("boiler.fluid_out", "mixer.branch1_in")
        self.connect("chp.fluid_out", "mixer.branch2_in")
        self.connect("chp.power_out", "electricity_grid.power_in")
        self.connect("electricity_grid.power_out", "doublet.power_in")
        self.connect("degasser.gas_out", "air.gas_in")
        self.connect("boiler.flue_out", "air.gas_in")
        self.connect("chp.flue_out", "air.gas_in")
        self.connect("boiler.loss_out", "air.heat_in")
        self.connect("chp.loss_out", "air.heat_in")
        self.connect("mixer.fluid_out", "supply_out")
