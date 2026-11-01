"""A district heating network and a district cooling network on an aquifer store."""

from gemini.modules.declarations import Inlet, Outlet
from gemini.modules.environment import Atmosphere
from gemini.modules.grids import ElectricityGrid
from gemini.plants.atesplant import ATESPlant
from gemini.plants.districtnetwork import DistrictNetwork
from gemini.plants.plant import Plant
from gemini.types import Stream


class DistrictEnergyPlant(Plant):
    """Heating network on a geothermal supply and a cooling network on an ATES plant.

    A geothermal supply on ``hot_in`` feeds a heating network with two building substations. In
    parallel an aquifer thermal energy storage plant in its charge mode chills the water of a
    cooling network that serves one building, and the warmed groundwater is stored in the warm
    well. The return of the cooling network leaves on ``cold_out``; the caller feeds it back to
    ``cold_in`` at the next step.

    Not schedulable: its networks and its aquifer store take their inputs from the run.
    """

    def __init__(self):
        """Build both networks and the ATES plant and connect them to the grids."""
        super().__init__()

        # Modules
        self.heating = DistrictNetwork(consumers=2)
        self.ates = ATESPlant()
        self.cooling = DistrictNetwork(consumers=1, service="cooling")
        self.electricity_grid = ElectricityGrid()
        self.air = Atmosphere()

        # Inlets
        self.hot_in = Inlet(Stream)
        self.cold_in = Inlet(Stream)
        self.air_in = Inlet(Stream, kind="air")

        # Outlets
        self.hot_out = Outlet(Stream)
        self.cold_out = Outlet(Stream)

        # Connections
        self.connect("hot_in", "heating.supply_in")
        self.connect("air_in", "heating.air_in")
        self.connect("cold_in", "ates.return_in")
        self.connect("air_in", "cooling.air_in")
        self.connect("ates.supply_out", "cooling.supply_in")
        self.connect("electricity_grid.power_out", "heating.power_in")
        self.connect("electricity_grid.power_out", "ates.power_in")
        self.connect("electricity_grid.power_out", "cooling.power_in")
        self.connect("heating.loss_out", "air.heat_in")
        self.connect("ates.loss_out", "air.heat_in")
        self.connect("cooling.loss_out", "air.heat_in")
        self.connect("heating.return_out", "hot_out")
        self.connect("cooling.return_out", "cold_out")
