"""Circulation pump of a closed circuit: a fixed flow, a pressure rise and an efficiency."""

from gemini.modules._utils.cost import Equipment
from gemini.modules.declarations import Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.physics import energy, fluid, pumps
from gemini.types import (
    Efficiency,
    HydraulicPower,
    MassFlow,
    Power,
    Pressure,
    PressureDifference,
    Stream,
)


class CirculationPump(Equipment, Module):
    """Pump that sets the flow of a closed circuit and draws the electricity for it.

    The circuit carries ``flow`` whatever enters, and leaves at ``loop_pressure``, the static
    pressure the circuit is held at, so a loop through this module closes in flow and pressure.
    ``pressure_rise`` is the design head that covers the losses of the circuit, which are not
    modelled: the hydraulic power is ``Q dp``, the electricity that power over ``efficiency``.

    NOTE(refactor): all the electricity leaves as ``loss_out`` and the water keeps its temperature,
    so a building circuit gives the same temperatures as with no pump: in the real circuit the
    pumping work ends up as heat in it, which is small against the heat it carries. The module is
    first-law closed with that port.
    """

    equipment_kind = "circulation_pump"

    repr_fields = ("flow", "pressure_rise", "efficiency")

    def __init__(self):
        """Declare the flow, the pressure of the circuit and the efficiency."""
        super().__init__()

        # Parameters
        self.flow = Parameter(MassFlow, gt=0, description="Mass flow the circuit carries")
        self.pressure_rise = Parameter(
            PressureDifference, ge=0, description="Design pressure rise of the circulation pump"
        )
        self.loop_pressure = Parameter(
            Pressure, gt=0, description="Static pressure the circuit is held at"
        )
        self.efficiency = Parameter(
            Efficiency,
            default=pumps.DEFAULT_CIRCULATION_PUMP_EFFICIENCY,
            description="Overall efficiency of the pump: hydraulic power over electric power",
        )

        # Inlets
        self.fluid_in = Inlet(Stream)
        self.power_in = Inlet(Power, kind="electricity")

        # Outputs
        self.pumping_power = Output(HydraulicPower, description="Electric power drawn by the pump")

        # Outlets
        self.fluid_out = Outlet(Stream)
        self.loss_out = Outlet(Power, kind="heat")

    def forward(self, inlets):
        """Set the flow and the pressure of the circuit and draw the electricity."""

        # Outlets
        discharge = inlets.fluid_in.with_(m_dot=self.flow, p=self.loop_pressure)
        hydraulic = pumps.hydraulic_power(discharge.volumetric_flow(), self.pressure_rise)
        power_in = energy.input_power(hydraulic, self.efficiency)

        # Outputs
        self.pumping_power = hydraulic

        outlets = dict(fluid_out=discharge, loss_out=power_in, power_in=power_in)
        return outlets

    def capex(self, finance):
        """Return the cost of the pump from its shaft power at the nominal flow."""
        volume_flow = fluid.volume_flow(self.flow, self.fluid.properties(0, 0).rho_l)
        hydraulic = pumps.hydraulic_power(volume_flow, self.pressure_rise)
        return self.capex_of(finance, energy.input_power(hydraulic, self.efficiency))
