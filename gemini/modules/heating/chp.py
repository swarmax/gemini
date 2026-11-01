"""Gas-engine combined heat and power unit heating a water circuit."""

from gemini import ops
from gemini.errors import ValidationError
from gemini.modules._utils.cost import Equipment
from gemini.modules._utils.flow import require_forward
from gemini.modules.declarations import Control, Inlet, Outlet, Output, Parameter
from gemini.modules.heating import _burner
from gemini.modules.module import Module
from gemini.physics import combustion, heat_transfer
from gemini.types import Efficiency, Fraction, Fuel, Power, Stream, Temperature


class CHP(Equipment, Module):
    """Gas-engine combined heat and power unit heating a water circuit.

    ``load_fraction`` L is the electric output as a share of ``electric_capacity``; L = 0 means
    the engine is off. Fuel (lower heating value) follows the Willans line
    F = F_full * (f0 + (1 - f0) * L) for L > 0, with F_full = electric_capacity /
    electric_efficiency and f0 = ``no_load_fuel_fraction`` (Willans-line method in Heywood
    1988, Internal Combustion Engine Fundamentals: fuel flow at constant speed is close to
    linear in brake load). The default f0 = 0 keeps both efficiencies constant over load; a
    typical lean-burn gas engine has its electric efficiency fall by a few points at half load,
    which an f0 of 0.05 to 0.15 reproduces.

    Recoverable engine heat (jacket water, oil and exhaust heat exchanger) is
    thermal_efficiency * F; the circuit takes it up to ``maximum_outlet_temperature`` and a dump
    cooler rejects the rest (``dumped_heat``), so with no water flow all engine heat is dumped.
    heat_loss = F - electricity_generated - heat_recovered (exhaust, radiation and dumped heat),
    so the model is first-law closed.

    ``fuel_in`` brings the co-produced gas: the engine burns it first, up to its need, and takes
    the rest from the grid. It may draw grid gas when
    ``fuel_in`` comes from a ``GasMakeup`` or a ``GasGrid``; without that mark the fuel energy of
    the stream limits the load. ``fuel_in`` shows what it took and ``flue_out`` what burning left,
    as on ``Boiler``.

    Assumptions: steady operation at a constant thermal efficiency on the fuel basis, no
    minimum stable load or start-up losses, no pressure loss, constant liquid heat capacity.
    Validity: L in (0, 1] at rated speed; efficiencies at full load with
    electric_efficiency + thermal_efficiency <= 1 (typical gas engines: 0.35 to 0.44 electric,
    0.40 to 0.50 thermal, from manufacturer data).
    """

    equipment_kind = "chp"

    def __init__(self):
        """Declare engine design data, the heated water circuit and energy flows."""
        super().__init__()

        # Parameters
        self.electric_capacity = Parameter(Power, gt=0, description="Maximum electric output")
        self.electric_efficiency = Parameter(
            Efficiency, description="Electric output over fuel energy at full load"
        )
        self.thermal_efficiency = Parameter(
            Efficiency, description="Useful heat output over fuel energy"
        )
        self.no_load_fuel_fraction = Parameter(
            Fraction,
            default=0,
            lt=1,
            description="Fuel use at zero load as a share of the full-load fuel use",
        )
        self.maximum_outlet_temperature = Parameter(
            Temperature, description="Highest water temperature at the unit outlet"
        )

        # Inlets
        self.fluid_in = Inlet(Stream, kind="hot_water")
        self.fuel_in = Inlet(Stream, kind="gas", drawn=True)

        # Controls
        self.load_fraction = Control(
            Fraction,
            description=(
                "Electric output as a share of the electric capacity; zero switches the engine off"
            ),
        )

        # Outputs
        self.fuel = Output(Fuel, description="Fuel power burned (lower heating value)")
        self.dumped_heat = Output(
            Power, description="Heat rejected because the circuit could not take all of it"
        )

        # Outlets
        self.fluid_out = Outlet(Stream, kind="hot_water")
        self.flue_out = Outlet(Stream, kind="gas")
        self.power_out = Outlet(Power, kind="electricity")
        self.loss_out = Outlet(Power, kind="heat")

    def forward(self, inlets):
        """Heat the water circuit by the recovered engine heat and return the gas it burned."""

        # Outlets
        inlet, fuel = inlets.fluid_in, inlets.fuel_in
        values = self._performance(inlet, fuel)
        outlet = inlet.with_(T=values["fluid_out_T"])
        flue_out = _burner.flue_stream(values["fuel"], fuel)
        fuel_in = _burner.burned_stream(values["fuel"], fuel)

        # Outputs
        self.fuel = values["fuel"]
        self.dumped_heat = values["dumped_heat"]

        outlets = dict(
            fluid_out=outlet,
            flue_out=flue_out,
            power_out=values["electricity_generated"],
            loss_out=values["heat_loss"],
            fuel_in=fuel_in,
        )
        return outlets

    def capex(self, finance):
        """Return the cost of the engine from its electric capacity."""
        return self.capex_of(finance, self.electric_capacity)

    def _load(self, fuel):
        """Return the load: the commanded one, or less when the stream alone must cover it."""
        if _burner.has_grid(fuel):
            return self.load_fraction
        need = combustion.willans_fuel_input(
            self.load_fraction,
            self.electric_capacity,
            self.electric_efficiency,
            self.no_load_fuel_fraction,
        )
        return combustion.covered_load(self.load_fraction, need, _burner.available_fuel(fuel))

    def _performance(self, inlet, fuel_in):
        """Return fuel, electricity, heat flows [W] and the outlet temperature [K]."""
        ops.check(
            self.electric_efficiency + self.thermal_efficiency <= 1,
            ValidationError,
            "{path}: electric_efficiency + thermal_efficiency = {total}; expected <= 1",
            path=self.path,
            total=self.electric_efficiency + self.thermal_efficiency,
            code="invalid_design",
        )
        require_forward(self.path, "fluid_in.m_dot", inlet.m_dot)
        load = self._load(fuel_in)
        fuel = combustion.willans_fuel_input(
            load, self.electric_capacity, self.electric_efficiency, self.no_load_fuel_fraction
        )
        engine_heat, generated = combustion.engine_energy_flows(
            fuel, load, self.electric_capacity, self.thermal_efficiency
        )
        rate = inlet.heat_capacity_rate()
        recovered = ops.minimum(
            engine_heat,
            heat_transfer.setpoint_duty(rate, self.maximum_outlet_temperature - inlet.T),
        )
        return {
            "fuel": fuel,
            "electricity_generated": generated,
            "heat_recovered": recovered,
            "dumped_heat": engine_heat - recovered,
            "heat_loss": fuel - generated - recovered,
            "fluid_out_T": inlet.T + heat_transfer.temperature_change(recovered, rate),
        }
