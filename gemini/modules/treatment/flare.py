"""Flare that burns the gas reaching it and reports what it emits."""

from gemini.modules._utils.cost import Equipment
from gemini.modules._utils.flow import require_forward
from gemini.modules.declarations import Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.physics import combustion, gas
from gemini.types import Efficiency, Fuel, MassFlow, Power, Stream
from gemini.types.fluid import FLUE_CO2, Fluid


class Flare(Equipment, Module):
    """Flare burning its inlet gas, with the CO2 and methane its composition gives.

    ``flue_out`` carries the CO2 the gas carries plus what burning forms and the methane that passes
    unburnt, to ``Atmosphere.gas_in``; ``combustion_efficiency`` defaults to 98 % (US EPA, AP-42,
    5th ed., section 13.5 "Industrial Flares", 2018). ``burned_mass_flow`` closes ``mass_balance``.
    The chemical power burned is ``fuel``; it leaves as heat through ``loss_out``.
    """

    equipment_kind = "flare"

    def __init__(self):
        """Declare the efficiency, the inlet and the emissions."""
        super().__init__()

        # Parameters
        self.combustion_efficiency = Parameter(
            Efficiency,
            default=float(combustion.FLARE_EFFICIENCY),
            structural=True,
            description="Share of the flared gas burned completely",
        )

        # Inlets
        self.gas_in = Inlet(Stream, kind="gas")

        # Outputs
        self.burned_mass_flow = Output(MassFlow, description="Mass flow of gas burned")
        self.fuel = Output(
            Fuel, description="Chemical power of the fuel burned (lower heating value)"
        )

        # Outlets
        self.flue_out = Outlet(Stream, kind="gas")
        self.loss_out = Outlet(Power, kind="heat")

    def forward(self, inlets):
        """Refuse reverse flow and release what burning leaves."""

        # Outlets
        require_forward(self.path, "gas_in.m_dot", inlets.gas_in.m_dot)
        inlet = inlets.gas_in
        co2, methane = self._released(inlet, inlet.m_dot)
        flue_out = inlet.with_(m_dot=co2 + methane, fluid=self._flue_fluid(inlet))

        loss_out = combustion.released_heat(
            inlet.m_dot, inlet.fluid.heating_value(), self.combustion_efficiency
        )

        # Outputs
        self.burned_mass_flow = inlets.gas_in.m_dot
        self.fuel = loss_out

        outlets = dict(flue_out=flue_out, loss_out=loss_out)
        return outlets

    def _released(self, inlet, mass_flow):
        """Return the CO2 and the methane [kg/s] that burning ``mass_flow`` of ``inlet`` leaves."""
        composition = inlet.fluid.gas_composition or {}
        carried, formed, methane = 0.0, 0.0, 0.0
        if composition:
            carried = gas.mass_fraction(composition, "CO2")
            formed = gas.combustion_co2(composition)
            methane = gas.mass_fraction(composition, "CH4")
        return combustion.burnt_gas_emissions(
            mass_flow, carried, formed, methane, self.combustion_efficiency
        )

    def _flue_fluid(self, inlet):
        """Return the fluid of the flue: one composition holds for every row of one fluid."""
        if inlet.fluid.gas_composition is None:
            return FLUE_CO2
        co2, methane = self._released(inlet, 1.0)
        return Fluid(
            kind="gas", gas_composition=gas.composition_of_masses({"CO2": co2, "CH4": methane})
        )

    def capex(self, finance):
        """Return the cost of the flare, a fixed item."""
        return self.capex_of(finance, 1)
