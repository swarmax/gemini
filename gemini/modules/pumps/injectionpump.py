"""Injection pump using supplied curves or a discharge-pressure setpoint."""

from gemini import ops
from gemini.errors import PhysicsError, ValidationError
from gemini.modules._utils.cost import Equipment
from gemini.modules._utils.flow import require_forward
from gemini.modules.declarations import Control, Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.modules.pumps import _physics
from gemini.physics import energy, pumps
from gemini.types import (
    Count,
    Efficiency,
    Frequency,
    Power,
    Pressure,
    PressureDifference,
    Stream,
    VolumeFlow,
)


class InjectionPump(Equipment, Module):
    """Raise brine pressure with a simple hydraulic-power estimate.

    The pump is equipment of the kind ``injection_pump``, priced per W of shaft power at the
    design point ``nominal_flow`` (and ``nominal_head`` for a pump with no curves). A plant that
    wires the doublets to a plant-level pump has one pump for all of them, so its ``nominal_flow``
    is their total; a ``NodalDoublet`` holds a pump of its own for its one injection limb. A
    ``Doublet`` has no injection pump and prices only its production pump, so no pump is counted
    twice. ``gm.study.size`` rates the pump of a plant from the doublets it serves.
    """

    equipment_kind = "injection_pump"

    repr_fields = ("stage_count", "efficiency", "pump_type")

    def __init__(self):
        """Declare injection pump design data, ports and controls."""
        super().__init__()

        # Parameters
        self.stage_count = Parameter(
            Count | None,
            default=None,
            description="Number of stages of the pump; empty when it has no curves",
        )
        self.pump_type = Parameter(
            str, default="unspecified", description="Catalogue name or label of the pump model"
        )
        self.efficiency = Parameter(
            Efficiency | None,
            default=None,
            calibratable=True,
            description="Overall efficiency of the pump; empty derives it from the curves",
        )
        self.head_coefficients = Parameter(
            list[float] | None,
            default=None,
            shape=(pumps.POLYNOMIAL_COEFFICIENT_COUNT,),
            description=(
                "Polynomial coefficients of the head curve of one stage; empty when not given"
            ),
        )
        self.power_coefficients = Parameter(
            list[float] | None,
            default=None,
            shape=(pumps.POLYNOMIAL_COEFFICIENT_COUNT,),
            description=(
                "Polynomial coefficients of the power curve of one stage; empty when not given"
            ),
        )

        self.nominal_flow = Parameter(
            VolumeFlow | None,
            default=None,
            description=(
                "Design volume flow of the pump, the basis of its price; empty when not sized"
            ),
        )
        self.nominal_head = Parameter(
            PressureDifference | None,
            default=None,
            description=(
                "Design pressure rise of the pump, for a pump with no curves; empty when not sized"
            ),
        )

        # Inlets
        self.fluid_in = Inlet(Stream, kind="brine")
        self.power_in = Inlet(Power, kind="electricity")

        # Controls
        self.pressure_setpoint = Control(
            Pressure | None,
            default=None,
            description=(
                "Discharge pressure the pump delivers; empty leaves the pressure rise to the "
                "frequency"
            ),
        )
        self.frequency = Control(
            Frequency,
            default=pumps.DEFAULT_INJECTION_PUMP_FREQUENCY,
            description="Operating frequency of the pump motor",
        )

        # Outputs
        self.head = Output(
            PressureDifference, soft_sensor=True, description="Pressure rise given to the stream"
        )
        self.power = Output(
            Power, soft_sensor=True, description="Mechanical power on the pump shaft"
        )
        self.discharge_pressure = Output(
            Pressure, soft_sensor=True, description="Pressure at the pump discharge"
        )
        self.is_pumping = Output(bool, description="True when the pump is running")

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
        self.is_pumping = head > 0

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
        curve. A setpoint below the suction pressure needs no pumping: the rise is zero, so the power
        is zero and the discharge pressure is the suction pressure (``is_pumping`` is false). A
        head curve that falls below zero is still an error.
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
            return ops.maximum(rise, 0.0)
        raise ValidationError(
            f"{self.path}: supply the pressure_setpoint control or head_coefficients and "
            "stage_count",
            code="invalid_design",
        )

    def capex(self, finance):
        """Return the cost of the pump from its shaft power at the nominal flow.

        The power is the power curve at ``nominal_flow`` and the default frequency for a pump with
        both curves, else the hydraulic power of ``nominal_flow`` and ``nominal_head`` over the
        efficiency. A missing design value raises ``missing_value`` naming it.
        """
        if self.nominal_flow is None:
            raise _missing_design(self.path, "nominal_flow")
        if self.head_coefficients is not None and self.power_coefficients is not None:
            power = pumps.power(
                self.nominal_flow,
                float(pumps.DEFAULT_INJECTION_PUMP_FREQUENCY),
                self.stage_count,
                self.power_coefficients,
            )
            return self.capex_of(finance, power)
        if self.nominal_head is None:
            raise _missing_design(self.path, "nominal_head")
        if self.efficiency is None:
            raise _missing_design(self.path, "efficiency")
        hydraulic = pumps.hydraulic_power(self.nominal_flow, self.nominal_head)
        return self.capex_of(finance, energy.input_power(hydraulic, self.efficiency))


def _missing_design(path, name):
    """Return the error of a design value that the pump needs to be priced."""
    return ValidationError(
        f"{path}.{name} is missing; expected the design value that sizes the pump",
        path=f"{path}.{name}",
        code="missing_value",
    )
