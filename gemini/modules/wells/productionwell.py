"""Production well from the sandface to the wellhead, optionally split at an internal ESP."""

from typing import Literal

from gemini import ops
from gemini.errors import ValidationError
from gemini.modules.declarations import Inlet, Outlet, Output, Parameter
from gemini.modules.wells.well import _Well
from gemini.physics import fluid, heat_transfer
from gemini.types import Length, Power, Pressure, PressureDifference, Stream, Temperature


class ProductionWell(_Well):
    """Production-well pressure and temperature profile with integrity checks.

    ``segment`` selects the traversed interval: the full well, the part below an internal ESP
    (sandface to intake) or the part above it (discharge to wellhead).

    NOTE(refactor): ``esp_depth`` cuts the pipe path as a number, so one graph serves any ESP
    depth: every section stays in the traversal, with the length that lies in the segment. The
    ``section_pressure`` and ``section_temperature`` list outputs are vector outputs of the graph,
    one item per section of the path, a section outside the segment giving the pressure and
    temperature it was entered at.
    """

    repr_fields = ("segment", "esp_depth", "soil_temperature", "heat_transfer_coefficient")

    def __init__(self):
        """Declare production-well geometry, inlet and outputs."""
        super().__init__()

        # Parameters
        self.segment = Parameter(Literal["full", "below_esp", "above_esp"], default="full")
        self.esp_depth = Parameter(Length | None, default=None)

        # Inlets
        self.bottom_in = Inlet(Stream, kind="brine")

        # Outputs
        self.friction_pressure_drop = Output(PressureDifference)
        self.gravity_pressure_drop = Output(PressureDifference)
        self.section_pressure = Output(list[Pressure])
        self.section_temperature = Output(list[Temperature])

        # Outlets
        self.wellhead_out = Outlet(Stream, kind="brine")
        self.loss_out = Outlet(Power, kind="heat")

    def forward(self, inlets):
        """Traverse the selected segment upward and apply the pressure correction."""

        # Outlets
        bottom = inlets.bottom_in
        start, end = self._segment_interval()
        result = self.traverse(bottom, start, end, "up")
        wellhead = self.corrected(bottom, result)

        # Outputs
        self.friction_pressure_drop = result.friction_pressure_drop
        self.gravity_pressure_drop = result.gravity_pressure_drop
        self.section_pressure = result.section_pressure
        self.section_temperature = result.section_temperature

        outlets = dict(wellhead_out=wellhead, loss_out=self._loss(bottom, wellhead))
        return outlets

    def _loss(self, bottom, wellhead):
        """Return the heat [W] the well gives to the rock between its two ends."""
        capacity_rate = fluid.heat_capacity_rate(
            wellhead.m_dot, bottom.fluid.properties(bottom.p, bottom.T).cp_l
        )
        return heat_transfer.heat_rate(capacity_rate, bottom.T - wellhead.T)

    def intake_conditions(self, bottom_stream):
        """Traverse from the sandface to ESP intake, returning a stream in SI units."""
        result = self.traverse(bottom_stream, self.total_length, self._esp_depth(), "up")
        return self.corrected(bottom_stream, result)

    def wellhead_from_discharge(self, discharge_stream):
        """Traverse from ESP discharge to wellhead, returning a stream in SI units."""
        result = self.traverse(discharge_stream, self._esp_depth(), 0, "up")
        return self.corrected(discharge_stream, result)

    def discharge_from_wellhead(self, wellhead_stream):
        """Infer ESP discharge from measured wellhead conditions using downward traversal."""
        result = self.traverse(wellhead_stream, 0, self._esp_depth(), "down")
        return self.corrected(wellhead_stream, result)

    def _drilled_length(self):
        """Return the length [m] of the selected segment of the well."""
        start, end = self._segment_interval()
        return abs(start - end)

    def _segment_interval(self):
        """Return the measured-depth interval [m] the selected segment traverses upward."""
        if self.segment == "below_esp":
            return self.total_length, self._esp_depth()
        if self.segment == "above_esp":
            return self._esp_depth(), 0
        return self.total_length, 0

    def _esp_depth(self):
        depth = self.esp_depth
        if depth is None:
            raise ValidationError(
                f"{self.path}: esp_depth = None is not configured within the "
                f"{self.total_length} m path",
                code="invalid_design",
            )
        ops.check(
            depth <= self.total_length,
            ValidationError,
            "{path}: esp_depth = {depth} m is not configured within the {total} m path",
            code="invalid_design",
            path=self.path,
            depth=depth,
            total=self.total_length,
        )
        return depth
