"""Geothermal heating: doublet, exchanger, peak boiler and the heating consumer."""

from gemini.modules.container import ModuleDict
from gemini.modules.environment import Atmosphere
from gemini.modules.exchangers import HeatExchanger
from gemini.modules.grids import ElectricityGrid, GasGrid, HeatingGrid
from gemini.modules.heating import Boiler
from gemini.modules.piping import GasMakeup, Pipe
from gemini.modules.pumps import InjectionPump
from gemini.modules.treatment import Degasser, Filter, Flare
from gemini.plants._utils.doublets import DoubletsPlant
from gemini.plants._utils.wiring import connect_gas


class HeatingPlant(DoubletsPlant):
    """Geothermal heating: doublet, heat exchanger, peak boiler and the heating consumer."""

    purpose = "heating"

    def __init__(self, doublets=1):
        """Declare the modules, ports and connections on ``doublets`` doublets."""
        super().__init__(doublets)

        # Modules
        self.degasser = Degasser()
        self.filters = ModuleDict({"hot": Filter(), "cold": Filter()})
        self.heat_exchanger = HeatExchanger()
        self.injection_pump = InjectionPump()
        self.heating_return_pipe = Pipe()
        self.peak_boiler = Boiler()
        self.heating_supply_pipe = Pipe()
        self.heating_consumer = HeatingGrid()
        self.gas_grid = GasGrid()
        self.electricity_grid = ElectricityGrid()
        self.gas_makeup = GasMakeup()
        self.flare = Flare()
        self.atmosphere = Atmosphere()

        # Connections
        connect_gas(self)
        self._connect_production("degasser.fluid_in")
        self.connect("degasser.liquid_out", "filters.hot.fluid_in")
        self.connect("filters.hot.fluid_out", "heat_exchanger.hot_in")
        self.connect("filters.cold.fluid_out", "injection_pump.fluid_in")
        self._connect_injection("injection_pump.fluid_out")
        self.connect("heating_return_pipe.fluid_out", "heat_exchanger.cold_in")
        self.connect("heating_supply_pipe.fluid_out", "heating_consumer.supply_in")
        self._connect_power("electricity_grid.power_out")
        self.connect("electricity_grid.power_out", "injection_pump.power_in")
        self.connect("heating_consumer.return_out", "heating_return_pipe.fluid_in")
        self.connect("atmosphere.air_out", "heating_return_pipe.air_in")
        self.connect("atmosphere.air_out", "heating_supply_pipe.air_in")
        self.connect("peak_boiler.flue_out", "atmosphere.gas_in")
        self.connect("flare.flue_out", "atmosphere.gas_in")
        self.connect("flare.loss_out", "atmosphere.heat_in")
        self.connect("heating_return_pipe.loss_out", "atmosphere.heat_in")
        self.connect("heating_supply_pipe.loss_out", "atmosphere.heat_in")
        self.connect("peak_boiler.loss_out", "atmosphere.heat_in")
        self.connect("heat_exchanger.cold_out", "peak_boiler.fluid_in")
        self.connect("heat_exchanger.hot_out", "filters.cold.fluid_in")
        self.connect("peak_boiler.fluid_out", "heating_supply_pipe.fluid_in")
