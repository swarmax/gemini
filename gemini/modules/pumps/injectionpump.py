"""Injection pump using supplied curves or a discharge-pressure setpoint."""

from gemini import ops
from gemini.errors import PhysicsError, ValidationError
from gemini.modules._utils.flow import require_forward
from gemini.modules.declarations import Control, Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.modules.pumps import _physics
from gemini.physics import energy, pumps
from gemini.types import Count, Efficiency, Frequency, Power, Pressure, PressureDifference, Stream


class InjectionPump(Module):
    """Raise brine pressure with a simple hydraulic-power estimate."""

    repr_fields = ("stage_count", "efficiency", "pump_type")

    def __init__(self):
        """Declare injection pump design data, ports and controls."""
        super().__init__()

        # Parameters
        self.stage_count = Parameter(Count | None, default=None)
        self.pump_type = Parameter(str, default="unspecified")
        self.efficiency = Parameter(Efficiency | None, default=None, calibratable=True)
        self.head_coefficients = Parameter(
            list[float] | None, default=None, shape=(pumps.POLYNOMIAL_COEFFICIENT_COUNT,)
        )
        self.power_coefficients = Parameter(
            list[float] | None, default=None, shape=(pumps.POLYNOMIAL_COEFFICIENT_COUNT,)
        )

        # Inlets
        self.fluid_in = Inlet(Stream, kind="brine")
        self.power_in = Inlet(Power, kind="electricity")

        # Controls
        self.pressure_setpoint = Control(Pressure | None, default=None)
        self.frequency = Control(Frequency, default=pumps.DEFAULT_INJECTION_PUMP_FREQUENCY)

        # Outputs
        self.head = Output(PressureDifference, soft_sensor=True)
        self.power = Output(Power, soft_sensor=True)
        self.discharge_pressure = Output(Pressure, soft_sensor=True)

        # Outlets
        self.fluid_out = Outlet(Stream, kind="brine")

    def forward(self, inlets):
        """Raise pressure from a supplied curve or discharge-pressure setpoint."""

        # Outlets
        suction = inlets.fluid_in
        head = self._head(suction)
        ops.check(
            head >= 0,
            PhysicsError,
            "{path}: head = {head} Pa; discharge pressure is below suction pressure",
            path=self.path,
            head=head,
        )

        discharge = suction.with_(p=suction.p + head)
        power_in = self._power(suction, head)

        # Outputs
        self.head = discharge.p - suction.p
        self.power = power_in
        self.discharge_pressure = discharge.p

        outlets = dict(fluid_out=discharge, power_in=power_in)
        return outlets

    def _power(self, suction, head):
        """Return the pump power [W] from the power curve, else from the efficiency.

        The efficiency has no default: a design states it, unless it has both curves.
        """
        flow = suction.volumetric_flow()
        if self.head_coefficients is not None and self.power_coefficients is not None:
            return pumps.power(flow, self.frequency, self.stage_count, self.power_coefficients)
        if self.efficiency is None:
            raise ValidationError(
                f"{self.path}: efficiency = None; expected a value, or head and power curves",
                path="efficiency",
                code="missing_value",
            )
        return energy.input_power(pumps.hydraulic_power(flow, head), self.efficiency)

    def _head(self, suction):
        """Return the pressure rise [Pa] from the head curve, else from the pressure setpoint.

        A ``power_coefficients`` curve is used for power only together with a ``head_coefficients``
        curve. A pump without flow cannot lower the pressure: a setpoint below its suction is then
        no rise, not an error.
        """
        flow = suction.volumetric_flow()
        require_forward(self.path, "suction volume flow", flow, "m3/s")
        if self.head_coefficients is not None:
            if self.stage_count is None:
                raise ValidationError(
                    f"{self.path}: head_coefficients curves require stage_count",
                    code="invalid_design",
                )
            return _physics.head(flow, self.frequency, self.stage_count, self.head_coefficients)
        if self.pressure_setpoint is not None:
            rise = self.pressure_setpoint - suction.p
            return ops.where(flow > 0, rise, ops.maximum(rise, 0.0))
        raise ValidationError(
            f"{self.path}: supply the pressure_setpoint control or head_coefficients and "
            "stage_count",
            code="invalid_design",
        )
