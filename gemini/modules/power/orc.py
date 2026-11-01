"""Binary organic Rankine cycle plant driven by geothermal brine, with an air-cooled condenser."""

from gemini.modules._utils.flow import require_forward
from gemini.modules.declarations import Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.modules.power import _physics
from gemini.physics import heat_transfer
from gemini.types import Efficiency, Fraction, Power, Stream, Temperature, TemperatureDifference


class ORC(Module):
    """Binary ORC plant: the brine heats the cycle, an air-cooled condenser rejects the rest.

    The working fluid condenses at T_c = ambient_temperature + condenser_approach. At design
    the brine is cooled to T_out = max(minimum_brine_outlet_temperature, T_c + pinch); the
    second term keeps the preheater pinch above the condensate. The working fluid sees the
    brine ``pinch`` colder, between T_a = T_in - pinch and T_b = T_out - pinch, so the
    reversible (Lorenz, triangular-cycle) work of the heat input Q = m cp (T_in - T_out) is
    W_rev = m cp ((T_a - T_b) - T_c ln(T_a / T_b)), that is Q (1 - T_c / T_lm) with the
    logarithmic mean T_lm of T_a and T_b. The gross power is ``carnot_fraction`` W_rev
    (DiPippo, R. (2007), Ideal thermal efficiency for geothermal binary plants, Geothermics
    36, 276-285; DiPippo, R. (2016), Geothermal Power Plants, 4th ed., chapter 8).
    ``carnot_fraction`` is plant specific: second-law efficiencies of operating binary
    plants are roughly 0.3 to 0.6 (DiPippo, R. (2004), Second Law assessment of binary plants
    generating power from low-temperature geothermal fluids, Geothermics 33, 565-586).

    When the gross power would exceed ``capacity``, part of the brine bypasses the plant: the
    processed share is capacity / uncapped gross power and ``fluid_out`` is the adiabatic mix
    of bypassed and cooled brine. The cycle efficiency is unchanged at part load (part-load
    degradation is not modelled). An inlet no hotter than T_out produces nothing and leaves
    unchanged.

    The parasitic loads (feed pump, condenser fans, controls) take ``parasitic_fraction`` of the
    gross power and are supplied from it, so ``power_out`` is the net power and
    ``parasitic_power`` is reported separately, not as ``power_in`` (which would count it
    twice in plant totals). The parasitic power ends as heat in the air: ``loss_out`` is the
    condenser duty plus the parasitic power. First law: heat_input = gross_power +
    condenser_duty and heat_input = electricity_generated + heat_loss, so ``energy_balance``
    closes with the brine's constant ``cp_l``. ``thermal_efficiency`` is net power over heat
    input (DiPippo 2016), ``None`` without heat input. Valid for a single-phase liquid brine.
    """

    def __init__(self):
        """Declare ORC design data, brine ports, ambient boundary and computed performance."""
        super().__init__()

        # Parameters
        self.minimum_brine_outlet_temperature = Parameter(Temperature)
        self.pinch = Parameter(TemperatureDifference, ge=0)
        self.carnot_fraction = Parameter(Efficiency)
        self.condenser_approach = Parameter(TemperatureDifference, ge=0)
        self.parasitic_fraction = Parameter(Fraction, lt=1)
        self.capacity = Parameter(Power, gt=0)

        # Inlets
        self.fluid_in = Inlet(Stream, kind="brine")
        self.air_in = Inlet(Stream, kind="air")

        # Outputs
        self.gross_power = Output(Power)
        self.parasitic_power = Output(Power)
        self.condenser_duty = Output(Power)
        self.thermal_efficiency = Output(Fraction | None)
        self.condensing_temperature = Output(Temperature)
        self.is_capped = Output(bool)

        # Outlets
        self.fluid_out = Outlet(Stream, kind="brine")
        self.power_out = Outlet(Power, kind="electricity")
        self.loss_out = Outlet(Power, kind="heat")

    def forward(self, inlets):
        """Cool the brine by the heat the cycle takes at the operating point."""

        # Outlets
        fluid_in = inlets.fluid_in
        design = self._design(fluid_in, inlets.air_in)
        fluid_out_T = heat_transfer.effectiveness_outlet_temperature(
            fluid_in.T, design.processed_share, design.outlet_temperature
        )

        fluid_out = fluid_in.with_(T=fluid_out_T)
        balance = self._balance(fluid_in, fluid_out, design)

        # Outputs
        self.gross_power = balance.gross_power
        self.parasitic_power = balance.parasitic_power
        self.condenser_duty = balance.condenser_duty
        self.thermal_efficiency = balance.thermal_efficiency
        self.condensing_temperature = design.condensing_temperature
        self.is_capped = design.is_capped

        outlets = dict(
            fluid_out=fluid_out, power_out=balance.electricity_generated, loss_out=balance.heat_loss
        )
        return outlets

    def _balance(self, fluid_in, fluid_out, design):
        """Return the energy balance of the plant at the operating point."""
        return _physics.plant_balance(
            heat_transfer.heat_rate(fluid_in.heat_capacity_rate(), fluid_in.T - fluid_out.T),
            design.cycle_efficiency,
            self.parasitic_fraction,
        )

    def _design(self, fluid_in, air):
        """Return the ``_physics.cycle_design`` of the brine inlet."""
        require_forward(self.path, "fluid_in.m_dot", fluid_in.m_dot)
        cp = fluid_in.fluid.properties(fluid_in.p, fluid_in.T).cp_l
        return _physics.cycle_design(
            fluid_in.T,
            fluid_in.m_dot,
            cp,
            air.T,
            self.condenser_approach,
            self.pinch,
            self.minimum_brine_outlet_temperature,
            self.carnot_fraction,
            self.capacity,
        )
