"""Dry or wet (evaporative) closed-circuit cooler rejecting heat to ambient air."""

from typing import Literal

from gemini import ops
from gemini.errors import ValidationError
from gemini.modules._utils.cost import Equipment
from gemini.modules._utils.flow import require_forward
from gemini.modules.declarations import Control, Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.physics import dispatch, heat_transfer, psychrometrics
from gemini.types import (
    WATER,
    MassFlow,
    Power,
    Pressure,
    Ratio,
    SpecificEnthalpy,
    Stream,
    Temperature,
    TemperatureDifference,
)


class Cooler(Equipment, Module):
    """Dry or wet (evaporative) closed-circuit cooler rejecting heat to ambient air.

    The fluid is cooled towards ``temperature_setpoint`` but not below the air on ``air_in`` plus
    ``approach``: connect ``Atmosphere.air_out`` for a ``dry`` cooler and ``Atmosphere.wet_air_out``
    for a ``wet`` one. The removed duty is capped at ``capacity``. Fans draw electricity =
    specific_fan_power * duty; the fan work is dissipated into the air stream, so the air on
    ``air_out`` takes up duty + electricity and the model is first-law closed.

    On a closed water loop ``loop_pressure`` and the control ``flow`` set ``fluid_out``, offered at
    the setpoint before the other modules run; ``is_capped`` tells when the cooler cannot reach it.

    A wet cooler is a closed-circuit evaporative fluid cooler: spray water evaporates on the
    outside of the coil, so the process stream keeps its mass flow and the evaporated water is
    reported as evaporation_rate = duty / latent_heat (default 2430 kJ/kg, water at about
    30 degC from the IAPWS-IF97 saturation tables). Taking all rejected heat as latent gives
    an upper bound (rules of thumb put about 80 to 90 % of the heat into evaporation); make-up
    water also covers drift and blowdown, which are not modelled.

    Assumptions: fixed approach at every load (the outlet limit does not improve at part load),
    fan power proportional to duty (speed-controlled fans, no cubic fan law), no pressure loss,
    constant liquid heat capacity. Validity: ambient air of about -20 to 45 degC; approach
    values of 5 to 15 K are typical for dry coolers and 3 to 8 K for wet coolers (ASHRAE
    Handbook, HVAC Systems and Equipment, chapters on cooling towers and dry coolers).
    """

    equipment_kind = "cooler"

    def __init__(self):
        """Declare cooler design data, the cooled stream, ambient air and energy flows."""
        super().__init__()
        self.fluid = WATER

        # Parameters
        self.cooler_type = Parameter(
            Literal["dry", "wet"],
            description="Heat rejection type: dry air cooler or wet (evaporative) cooler",
        )
        self.capacity = Parameter(
            Power, gt=0, description="Largest heat duty the cooler can reject"
        )
        self.approach = Parameter(
            TemperatureDifference,
            ge=0,
            description="Smallest temperature difference between the cooled fluid and the air",
        )
        self.specific_fan_power = Parameter(
            Ratio, description="Fan electricity per unit of heat rejected"
        )
        self.loop_pressure = Parameter(
            Pressure | None,
            default=None,
            structural=True,
            description=(
                "Static pressure the closed loop is held at; empty leaves the pressure of the "
                "stream"
            ),
        )
        self.latent_heat = Parameter(
            SpecificEnthalpy,
            default=psychrometrics.DEFAULT_LATENT_HEAT,
            gt=0,
            description="Latent heat of vaporization of the evaporated water",
        )

        # Inlets
        self.fluid_in = Inlet(Stream, kind="hot_water")
        self.air_in = Inlet(Stream, kind="air", drawn=True)
        self.power_in = Inlet(Power, kind="electricity")

        # Controls
        self.temperature_setpoint = Control(
            Temperature, description="Outlet temperature the cooler cools the fluid towards"
        )

        self.flow = Control(
            MassFlow | None,
            default=None,
            ge=0,
            description="Mass flow of the cooled fluid; empty takes the stream flow",
        )

        # Outputs
        self.evaporation_rate = Output(
            MassFlow, description="Mass flow of water evaporated by a wet cooler"
        )
        self.is_capped = Output(bool, description="True when the duty was limited by the capacity")

        # Outlets
        self.fluid_out = Outlet(Stream, kind="hot_water", offered=True)
        self.air_out = Outlet(Stream, kind="air")

    def _offers(self):
        """Offer only on a closed loop; otherwise the outlet follows from the inlet."""
        return self.loop_pressure is not None

    def _offer(self, inlets):
        """Offer the water of a closed loop, at the setpoint and the given flow."""
        if self.loop_pressure is None or self.flow is None:
            raise ValidationError(
                f"{self.path}: loop_pressure and flow are needed to offer fluid_out; expected "
                "both on a closed loop",
                code="invalid_design",
            )
        offered = Stream._si(
            m_dot=self.flow, T=self.temperature_setpoint, p=self.loop_pressure, fluid=self.fluid
        )
        return {"fluid_out": offered}

    def forward(self, inlets):
        """Cool the stream by the rejected duty and heat the air by it and by the fan."""

        # Outlets
        inlet, air = inlets.fluid_in, inlets.air_in
        duty, rate, requested = self._duty(inlet, air)
        cooled = inlet.with_(T=inlet.T - heat_transfer.temperature_change(duty, rate))
        outlet = cooled if self.loop_pressure is None else self._offer(inlets)["fluid_out"]
        power_in = heat_transfer.fan_power(duty, self.specific_fan_power)
        air_in, air_out = self._air(air, cooled.T, duty + power_in)

        # Outputs
        self.evaporation_rate = (
            psychrometrics.evaporation_rate(duty, self.latent_heat)
            if self.cooler_type == "wet"
            else 0.0
        )
        self.is_capped = requested > self.capacity

        outlets = dict(fluid_out=outlet, air_out=air_out, air_in=air_in, power_in=power_in)
        return outlets

    def capex(self, finance):
        """Return the cost of the cooler from its capacity."""
        return self.capex_of(finance, self.capacity)

    def _air(self, air, water_T, heat):
        """Return the air taken and returned: it leaves at the cooled water, at least an approach.

        The flow follows from the heat it takes up. NOTE(refactor): a simple air-side balance; the
        fan curve is not modelled.
        """
        rise = ops.maximum(water_T - air.T, self.approach)
        specific_heat = air.fluid.properties(air.p, air.T).cp_l
        flow = ops.where(heat > 0, dispatch.circuit_flow(heat, specific_heat, rise), 0.0)
        return air.with_(m_dot=flow), air.with_(m_dot=flow, T=air.T + rise)

    def _duty(self, inlet, air):
        """Return the rejected duty [W], heat capacity rate [W/K] and uncapped request [W]."""
        require_forward(self.path, "fluid_in.m_dot", inlet.m_dot)
        target = ops.maximum(self.temperature_setpoint, air.T + self.approach)
        rate = inlet.heat_capacity_rate()
        requested = heat_transfer.setpoint_duty(rate, inlet.T - target)
        return ops.minimum(requested, self.capacity), rate, requested
