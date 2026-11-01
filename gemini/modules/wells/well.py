"""Shared design data and traversals of production and injection wells.

Both wells traverse a geothermal pipe path using the original GEMINI DPDT equations, Swamee–Jain
(1976) friction, Beggs–Brill two-phase flow and explicit heat loss.
"""

from typing import Literal

from gemini import ops
from gemini.errors import PhysicsError
from gemini.modules._utils.cost import Equipment
from gemini.modules.declarations import Parameter
from gemini.modules.module import Module
from gemini.physics import geometry, hydraulics
from gemini.types import (
    Angle,
    Dimensionless,
    HeatTransferCoefficient,
    Length,
    PressureDifference,
    Temperature,
)


class _Well(Equipment, Module):
    """Pipe path, correlations, soil heat loss and affine pressure correction of one well.

    The path is the parallel lists ``section_length``, ``section_inclination``, ``section_diameter``
    and ``section_roughness``, one item per constant-diameter section from the surface to the
    bottom; they are numeric parameters, so a graph traced for a well serves any lengths and
    diameters, as long as the number of sections stays (``pipe_path`` gives them as a
    ``PipePath``). ``flow_direction`` is the direction the brine flows: ``"up"`` in a production
    well and ``"down"`` in an injection well. A well is drilled: its capex is the drilling factor
    times the length it traverses.
    """

    abstract = True

    equipment_kind = "drilling"

    flow_direction = "up"

    def __init__(self):
        super().__init__()

        # Parameters
        self.section_length = Parameter(
            list[Length], description="Length of each section of the well path, from the surface down"
        )
        self.section_inclination = Parameter(
            list[Angle], description="Inclination of each section of the well path from the horizontal"
        )
        self.section_diameter = Parameter(
            list[Length], description="Inner diameter of each section of the well path"
        )
        self.section_roughness = Parameter(
            list[Length], description="Absolute roughness of each section of the well path"
        )
        self.friction_correlation = Parameter(
            Literal["darcy_weisbach"],
            default="darcy_weisbach",
            description="Correlation of the single-phase friction",
        )
        self.two_phase_friction_correlation = Parameter(
            Literal["BeggsBrill"],
            default="BeggsBrill",
            description="Correlation of the two-phase friction",
        )
        self.correction_factors = Parameter(
            tuple[Dimensionless, PressureDifference],
            default=(1, 0),
            calibratable=True,
            description=(
                "Calibration factors of the pressure change: a multiplier and an added pressure "
                "difference"
            ),
        )
        self.soil_temperature = Parameter(
            Temperature, description="Temperature of the soil around the well"
        )
        self.heat_transfer_coefficient = Parameter(
            HeatTransferCoefficient,
            default=hydraulics.DEFAULT_WELL_U_VALUE,
            ge=0,
            calibratable=True,
            description="Overall heat transfer coefficient from the fluid to the soil",
        )

    @property
    def pipe_path(self):
        """Return the validated ``PipePath`` of the section lists."""
        return geometry.path_of(
            self.section_length,
            self.section_inclination,
            self.section_diameter,
            self.section_roughness,
        )

    @property
    def total_length(self):
        """Return the measured length [m] of the path."""
        return sum(self.section_length)

    def capex(self, finance):
        """Return the cost of drilling the length of the well that this module traverses."""
        return self.capex_of(finance, self._drilled_length())

    def _drilled_length(self):
        """Return the measured length [m] of the well."""
        return self.total_length

    def traverse(self, stream, from_md: float, to_md: float, direction: Literal["up", "down"]):
        """Traverse an arbitrary depth interval [m], returning uncorrected SI conditions."""
        wrong = to_md > from_md if direction == "up" else to_md < from_md
        ops.check(
            ops.logical_not(wrong),
            PhysicsError,
            "{path}: depth interval {from_md} m -> {to_md} m conflicts with direction {direction}",
            path=self.path,
            from_md=from_md,
            to_md=to_md,
            direction=direction,
        )
        path = geometry.path_between(
            self.section_length,
            self.section_inclination,
            self.section_diameter,
            self.section_roughness,
            from_md,
            to_md,
        )
        return hydraulics.pipe_path_profile(
            path,
            stream,
            stream.fluid,
            direction,
            self.heat_transfer_coefficient,
            self.soil_temperature,
            self.friction_correlation,
            self.two_phase_friction_correlation,
        )

    def corrected(self, stream, result):
        """Return ``stream`` at the traversal outlet, with the affine pressure correction."""
        slope, offset = self.correction_factors
        pressure = hydraulics.affine_correction(result.p_out, slope, offset)
        return stream.with_(p=pressure, T=result.T_out)

    def corrosion_profile(
        self, stream, chemistry: dict | None = None, model: str = "NORSOK"
    ) -> list[float]:
        """Return per-section CO2 corrosion [mm/year] using SI chemistry inputs.

        Without ``chemistry`` the fluid supplies it, and a CO2-free fluid gives zero everywhere.
        NOTE(refactor): corrosion/erosion helpers retain their documented mm/year convention;
        physics and golden values are unchanged (explicit SI exception).
        """
        if chemistry is None:
            chemistry = stream.fluid.corrosion_inputs(stream.p, stream.T)
            if stream.fluid.co2_mass_fraction == 0:
                return [0.0 for _ in self.pipe_path.sections]
        return hydraulics.corrosion_profile(
            self.pipe_path,
            self._traversal_stream(stream),
            stream.fluid,
            self.flow_direction,
            self.heat_transfer_coefficient,
            self.soil_temperature,
            chemistry,
            model,
        )

    def erosion_check(self, stream) -> dict:
        """Compare section velocities [m/s] with the API erosional velocity limit."""
        return hydraulics.erosion_check(self.pipe_path, stream, stream.fluid)

    def _traversal_stream(self, stream):
        """Return the stream in the sign convention of the DPDT traversal."""
        return stream
