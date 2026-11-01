"""Electrical submersible pump using the retained TNO polynomial basis."""

import numpy as np

from gemini import ops, runtime
from gemini.modules._utils.flow import require_forward
from gemini.modules.declarations import Control, Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.modules.pumps import _physics
from gemini.ops import kernels
from gemini.physics import constants, diagnostics, energy, pumps
from gemini.types import (
    Count,
    Dimensionless,
    Efficiency,
    Fraction,
    Frequency,
    Health,
    Length,
    Power,
    Pressure,
    PressureDifference,
    Ratio,
    Stream,
    VolumeFlow,
)

HEALTH_KEYS = ("power", "head", "discharge_pressure")
"""Measured quantities whose relative drift from the prediction is scored."""

NO_MEASUREMENTS_OUTSIDE = "No performance measurements; outside operating window"


CURVE_SHAPE = (pumps.POLYNOMIAL_COEFFICIENT_COUNT,)
"""Shape of the head and power coefficient lists."""


def _float32():
    """Return whether the runtime precision is float32."""
    return runtime.get_precision() == "float32"


class ESP(Module):
    """Electrical submersible pump installed inside a production well."""

    repr_fields = ("stage_count", "setting_depth", "motor_efficiency", "best_efficiency_flow")

    def __init__(self):
        """Declare ESP design data, ports and computed performance."""
        super().__init__()

        # Parameters
        self.stage_count = Parameter(Count)
        self.head_coefficients = Parameter(list[float], shape=CURVE_SHAPE, calibratable=True)
        self.power_coefficients = Parameter(list[float], shape=CURVE_SHAPE, calibratable=True)
        self.pump_type = Parameter(str | None, default=None)
        self.setting_depth = Parameter(Length, default=0)
        self.motor_efficiency = Parameter(Efficiency, default=1)
        self.minimum_flow = Parameter(VolumeFlow, default=0, ge=0)
        self.maximum_flow = Parameter(VolumeFlow, default=1, gt=0)
        self.best_efficiency_flow = Parameter(VolumeFlow, default=pumps.DEFAULT_BEP_FLOW, gt=0)
        self.correction_factors = Parameter(
            tuple[Dimensionless, PressureDifference], default=(1, 0)
        )
        self.tubing = Parameter(Length | None, default=None, gt=0)
        self.drift_threshold = Parameter(
            Fraction, default=diagnostics.DEFAULT_DRIFT_THRESHOLD, gt=0, le=1
        )

        # Inlets
        self.fluid_in = Inlet(Stream, kind="brine")
        self.power_in = Inlet(Power, kind="electricity")

        # Controls
        self.frequency = Control(Frequency)

        # Outputs
        self.head = Output(PressureDifference, soft_sensor=True)
        self.power = Output(Power, soft_sensor=True)
        self.efficiency = Output(Dimensionless, soft_sensor=True)
        self.discharge_pressure = Output(Pressure, soft_sensor=True)
        self.is_in_operating_window = Output(bool)
        self.best_efficiency_ratio = Output(Ratio)

        # Outlets
        self.fluid_out = Outlet(Stream, kind="brine")

    def _scalar_mode(self):
        """Return ``PLAIN`` under float32 precision, else ``WRAP``.

        NOTE(refactor): the legacy float32 arithmetic needs Python floats next to float32
        coefficients, and an ``np.float64`` scalar would promote them. This is the one module that
        honours float32 precision, so ``_physics.esp_efficiency`` keeps ``ops.truediv``: a
        plain ``/`` by a zero power would raise there.
        """
        return kernels.PLAIN if _float32() else kernels.WRAP

    def forward(self, inlets):
        """Raise the suction-stream pressure by the pump-curve head."""

        # Outlets
        suction = inlets.fluid_in
        flow = suction.volumetric_flow()
        require_forward(self.path, "suction volume flow", flow, "m3/s")
        head = self.head_function(flow, self.frequency)

        discharge = suction.with_(p=suction.p + head)
        power = self.power_function(flow, self.frequency)
        power_in = energy.input_power(power, self.motor_efficiency)

        # Outputs
        self.head = head
        self.power = power
        self.efficiency = _physics.esp_efficiency(flow, self.head, self.power)
        scale = pumps.speed_ratio(self.frequency, constants.ESP_REFERENCE_FREQUENCY)
        self.discharge_pressure = discharge.p
        self.is_in_operating_window = pumps.is_in_operating_window(
            flow, self.minimum_flow, self.maximum_flow, scale
        )
        self.best_efficiency_ratio = pumps.best_efficiency_ratio(
            flow, scale, self.best_efficiency_flow
        )

        outlets = dict(fluid_out=discharge, power_in=power_in)
        return outlets

    def head_function(self, flow: float, frequency: float) -> float:
        """Return pump head [Pa] for flow [m3/s] and frequency [Hz]."""
        return _physics.head(
            flow, frequency, self.stage_count, self._coefficients(self.head_coefficients)
        )

    def power_function(self, flow: float, frequency: float) -> float:
        """Return shaft power [W] for flow [m3/s] and frequency [Hz]."""
        return pumps.power(
            flow, frequency, self.stage_count, self._coefficients(self.power_coefficients)
        )

    def health(self, result, measured):
        """Score the worst available relative drift and the operating window.

        Runs on scalars and on arrays over a chunk: the worst drift key and the message are
        selected with ``ops.where`` over complete strings, the first key winning a tie.
        """
        predicted = result.outputs
        window = predicted.is_in_operating_window
        drifts = {
            key: diagnostics.relative_drift(measured[key], getattr(predicted, key))
            for key in HEALTH_KEYS
            if key in measured
        }
        worst, message = self._worst_drift(drifts, window)
        return Health(
            score=diagnostics.remaining_margin(worst),
            alarm=ops.logical_or(worst > self.drift_threshold, ops.logical_not(window)),
            message=message,
            metrics=drifts,
        )

    @staticmethod
    def _worst_drift(drifts, window):
        """Return the largest absolute drift and the message naming it and the window."""
        if not drifts:
            return 0, ops.where(window, "No performance measurements", NO_MEASUREMENTS_OUTSIDE)
        worst, message = None, None
        for key, drift in drifts.items():
            text = ops.where(
                window, f"Worst drift: {key}", f"Worst drift: {key}; outside operating window"
            )
            magnitude = ops.abs(drift)
            if worst is None:
                worst, message = magnitude, text
                continue
            larger = magnitude > worst
            worst, message = ops.where(larger, magnitude, worst), ops.where(larger, text, message)
        return worst, message

    @staticmethod
    def _coefficients(values):
        """Return curve coefficients in the selected runtime precision.

        NOTE(refactor): old monitoring uses NumPy float32 arithmetic when selected globally. The
        ``np.asarray`` is a precision cast of the stored coefficients, not maths.
        """
        if _float32():
            return np.asarray(values, dtype=np.float32)
        return values
