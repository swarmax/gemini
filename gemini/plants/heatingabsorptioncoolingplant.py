"""Heating with a peak boiler and an absorption chiller on the hot water."""

from gemini.modules.container import ModuleDict
from gemini.modules.cooling import AbsorptionUnit
from gemini.modules.environment import Atmosphere
from gemini.modules.exchangers import Cooler, HeatExchanger
from gemini.modules.grids import CoolingGrid, ElectricityGrid, GasGrid, HeatingGrid
from gemini.modules.heating import Boiler
from gemini.modules.piping import GasMakeup, Mixer, Pipe, Splitter
from gemini.modules.pumps import InjectionPump
from gemini.modules.treatment import Degasser, Filter, Flare
from gemini.plants._utils.doublets import DoubletsPlant
from gemini.plants._utils.wiring import connect_cooler, connect_gas


class HeatingAbsorptionCoolingPlant(DoubletsPlant):
    """Heating with a peak boiler and an absorption chiller on the hot water."""

    purpose = "both"

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
        self.absorption_chiller = AbsorptionUnit()
        self.drive_splitter = Splitter()
        self.drive_mixer = Mixer()
        self.heating_supply_pipe = Pipe()
        self.heating_consumer = HeatingGrid()
        self.cooling_return_pipe = Pipe()
        self.cooling_supply_pipe = Pipe()
        self.cooling_consumer = CoolingGrid()
        self.gas_grid = GasGrid()
        self.electricity_grid = ElectricityGrid()
        self.gas_makeup = GasMakeup()
        self.flare = Flare()
        self.atmosphere = Atmosphere()
        self.absorption_cooler = Cooler()

        # Connections
        connect_gas(self)
        self._connect_production("degasser.fluid_in")
        self.connect("degasser.liquid_out", "filters.hot.fluid_in")
        self.connect("filters.hot.fluid_out", "heat_exchanger.hot_in")
        self.connect("filters.cold.fluid_out", "injection_pump.fluid_in")
        self._connect_injection("injection_pump.fluid_out")
        self.connect("heating_return_pipe.fluid_out", "drive_mixer.branch1_in")
        self.connect("drive_mixer.fluid_out", "heat_exchanger.cold_in")
        self.connect("peak_boiler.fluid_out", "drive_splitter.fluid_in")
        self.connect("drive_splitter.branch2_out", "absorption_chiller.generator_in")
        self.connect("heating_supply_pipe.fluid_out", "heating_consumer.supply_in")
        self.connect("cooling_return_pipe.fluid_out", "absorption_chiller.chilled_in")
        self.connect("cooling_supply_pipe.fluid_out", "cooling_consumer.supply_in")
        self._connect_power("electricity_grid.power_out")
        self.connect("electricity_grid.power_out", "injection_pump.power_in")
        self.connect("electricity_grid.power_out", "absorption_chiller.power_in")
        self.connect("heating_consumer.return_out", "heating_return_pipe.fluid_in")
        self.connect("cooling_consumer.return_out", "cooling_return_pipe.fluid_in")
        self.connect("atmosphere.air_out", "heating_return_pipe.air_in")
        self.connect("atmosphere.air_out", "heating_supply_pipe.air_in")
        self.connect("atmosphere.air_out", "cooling_return_pipe.air_in")
        self.connect("atmosphere.air_out", "cooling_supply_pipe.air_in")
        self.connect("peak_boiler.flue_out", "atmosphere.gas_in")
        self.connect("flare.flue_out", "atmosphere.gas_in")
        self.connect("flare.loss_out", "atmosphere.heat_in")
        connect_cooler(
            self,
            "absorption_chiller.cooling_out",
            "absorption_chiller.cooling_in",
            "absorption_cooler",
        )
        self.connect("heating_return_pipe.loss_out", "atmosphere.heat_in")
        self.connect("heating_supply_pipe.loss_out", "atmosphere.heat_in")
        self.connect("cooling_return_pipe.loss_out", "atmosphere.heat_in")
        self.connect("cooling_supply_pipe.loss_out", "atmosphere.heat_in")
        self.connect("peak_boiler.loss_out", "atmosphere.heat_in")
        self.connect("heat_exchanger.cold_out", "peak_boiler.fluid_in")
        self.connect("heat_exchanger.hot_out", "filters.cold.fluid_in")
        self.connect("absorption_chiller.generator_out", "drive_mixer.branch2_in")
        self.connect("drive_splitter.branch1_out", "heating_supply_pipe.fluid_in")
        self.connect("absorption_chiller.chilled_out", "cooling_supply_pipe.fluid_in")
