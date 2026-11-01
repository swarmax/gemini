"""Clean-filter quadratic hydraulic loss and clogging diagnostics."""

from gemini import ops, units
from gemini.modules.declarations import Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.modules.treatment import _physics
from gemini.physics import diagnostics, hydraulics, separation
from gemini.types import Health, MassFlow, PressureDifference, Stream


class Filter(Module):
    """Filter with a quadratic clean-filter pressure loss and a clogging alarm.

    Solids removal itself is not modelled.
    """

    def __init__(self):
        """Declare filter design data, inlet and computed pressure drop."""
        super().__init__()

        # Parameters
        self.nominal_pressure_drop = Parameter(
            PressureDifference,
            default=_physics.FILTER_NOMINAL_DROP,
            ge=0,
            description="Pressure drop of the clean filter at the nominal mass flow",
        )
        self.nominal_mass_flow = Parameter(
            MassFlow,
            default=_physics.FILTER_NOMINAL_MASS_FLOW,
            gt=0,
            description="Mass flow at which the clean-filter pressure drop holds",
        )
        self.clogging_pressure_drop = Parameter(
            PressureDifference,
            default=units.bar_to_pa(separation.FILTER_CLOGGING_BAR),
            gt=0,
            description="Pressure drop at which the clogging alarm is raised",
        )

        # Inlets
        self.fluid_in = Inlet(Stream, kind="brine")

        # Outputs
        self.pressure_drop = Output(
            PressureDifference, soft_sensor=True, description="Pressure lost through the filter"
        )

        # Outlets
        self.fluid_out = Outlet(Stream, kind="brine")

    def forward(self, inlets):
        """Apply a quadratic clean-filter pressure loss."""

        # Outlets
        inlet = inlets.fluid_in
        drop = self._pressure_drop(inlet)
        outlet = inlet.with_(p=inlet.p - drop)

        # Outputs
        self.pressure_drop = drop

        outlets = dict(fluid_out=outlet)
        return outlets

    def health(self, result, measured):
        """Alarm when measured filter pressure loss exceeds the clogging limit."""
        if "pressure_drop" not in measured:
            return None
        dp = measured["pressure_drop"]
        ratio = diagnostics.performance_ratio(ops.maximum(0, dp), self.clogging_pressure_drop)
        alarm = dp > self.clogging_pressure_drop
        return Health(
            score=diagnostics.remaining_margin(ratio),
            alarm=alarm,
            message=ops.where(
                alarm, "Filter pressure drop exceeds limit", "Filter pressure drop within limit"
            ),
            metrics={"pressure_drop": dp},
        )

    def _pressure_drop(self, inlet):
        """Return the clean-filter loss [Pa], quadratic in mass flow."""
        return hydraulics.quadratic_pressure_drop(
            self.nominal_pressure_drop, inlet.m_dot, self.nominal_mass_flow
        )
