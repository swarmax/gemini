"""Nodal doublet with three parallel heat exchangers on one secondary network."""

from gemini.modules.container import ModuleList
from gemini.modules.declarations import Inlet, Outlet
from gemini.modules.exchangers import HeatExchanger
from gemini.modules.grids import ElectricityGrid
from gemini.modules.piping import Mixer, Splitter
from gemini.modules.treatment import Degasser, Filter
from gemini.plants.nodaldoublet import NodalDoublet
from gemini.plants.plant import Plant
from gemini.types import Stream

SHARES = (0.5, 0.3, 0.2)
"""Shares of the primary and the secondary flow sent to each heat exchanger."""


class ParallelExchangerPlant(Plant):
    """Nodal doublet whose brine heats one secondary network through three parallel exchangers.

    The port of the upstream GEMINI simulator's ``parallel_hex_plant`` example. The producer is
    solved for its rate at the ``doublet.wellhead_pressure`` boundary; the brine passes a degasser
    and a filter, is divided over the exchangers in ``SHARES``, remixed, filtered again and
    injected, with the injection pump set to the wellhead pressure the injector needs. The
    secondary water is divided in the same shares, set as the ``split_fraction`` of the two
    splitter cascades, and remixed after the exchangers. ``gm.plants.example`` carries the well,
    reservoir, ESP and exchanger data of the upstream example.

    Not schedulable: its doublet is a ``NodalDoublet``, and a run sets its splits and setpoints.
    """

    def __init__(self):
        """Build the plant; the tees are cascades of two-way splitters and mixers."""
        super().__init__()
        tees = len(SHARES) - 1

        # Modules
        self.doublet = NodalDoublet()
        self.degasser = Degasser()
        self.inlet_filter = Filter()
        self.primary_splitters = ModuleList(Splitter() for _ in range(tees))
        self.secondary_splitters = ModuleList(Splitter() for _ in range(tees))
        self.heat_exchangers = ModuleList(HeatExchanger() for _ in SHARES)
        self.primary_mixers = ModuleList(Mixer() for _ in range(tees))
        self.secondary_mixers = ModuleList(Mixer() for _ in range(tees))
        self.outlet_filter = Filter()
        self.electricity_grid = ElectricityGrid()

        # Inlets
        self.return_in = Inlet(Stream)

        # Outlets
        self.supply_out = Outlet(Stream)
        self.gas_out = Outlet(Stream, kind="gas")

        # Connections
        self.connect("return_in", "secondary_splitters.0.fluid_in")
        self.connect("doublet.supply_out", "degasser.fluid_in")
        self.connect("degasser.liquid_out", "inlet_filter.fluid_in")
        self.connect("inlet_filter.fluid_out", "primary_splitters.0.fluid_in")
        self._divide("primary_splitters", "hot_in")
        self._divide("secondary_splitters", "cold_in")
        self._combine("primary_mixers", "hot_out")
        self._combine("secondary_mixers", "cold_out")
        self.connect(f"primary_mixers.{tees - 1}.fluid_out", "outlet_filter.fluid_in")
        self.connect("outlet_filter.fluid_out", "doublet.return_in")
        self.connect("electricity_grid.power_out", "doublet.power_in")
        self.connect(f"secondary_mixers.{tees - 1}.fluid_out", "supply_out")
        self.connect("degasser.gas_out", "gas_out")

    def _divide(self, cascade, port):
        """Connect a splitter cascade: each sends its share to an exchanger, the last the rest."""
        tees = len(SHARES) - 1
        for index in range(tees):
            self.connect(f"{cascade}.{index}.branch2_out", f"heat_exchangers.{index}.{port}")
            if index < tees - 1:
                self.connect(f"{cascade}.{index}.branch1_out", f"{cascade}.{index + 1}.fluid_in")
        self.connect(f"{cascade}.{tees - 1}.branch1_out", f"heat_exchangers.{tees}.{port}")

    def _combine(self, cascade, port):
        """Connect a mixer cascade over the exchangers, the running mix entering first."""
        running = f"heat_exchangers.0.{port}"
        for index in range(len(SHARES) - 1):
            self.connect(running, f"{cascade}.{index}.branch1_in")
            self.connect(f"heat_exchangers.{index + 1}.{port}", f"{cascade}.{index}.branch2_in")
            running = f"{cascade}.{index}.fluid_out"
