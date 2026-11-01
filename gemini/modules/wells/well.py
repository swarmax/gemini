"""Shared design data and traversals of production and injection wells.

Both wells traverse a geothermal pipe path using the original GEMINI DPDT equations, Swamee–Jain
(1976) friction, Beggs–Brill two-phase flow and explicit heat loss.
"""

from typing import Literal

from gemini.errors import PhysicsError
from gemini.modules._utils.cost import Equipment
from gemini.modules.declarations import Parameter
from gemini.modules.module import Module
from gemini.physics import geometry, hydraulics
from gemini.types import Dimensionless, HeatTransferCoefficient, PressureDifference, Temperature


class _Well(Equipment, Module):
    """Pipe path, correlations, soil heat loss and affine pressure correction of one well.

    ``flow_direction`` is the direction the brine flows: ``"up"`` in a production well and
    ``"down"`` in an injection well. A well is drilled: its capex is the drilling factor times
    the length it traverses.
    """

    abstract = True

    equipment_kind = "drilling"

    flow_direction = "up"

    def __init__(self):
        super().__init__()

        # Parameters
        self.pipe_path = Parameter(
            geometry.PipePath,
            description="Path of the well as a list of sections with depth, direction and diameter",
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

    def capex(self, finance):
        """Return the cost of drilling the length of the well that this module traverses."""
        return self.capex_of(finance, self._drilled_length())

    def _drilled_length(self):
        """Return the measured length [m] of the well."""
        return self.pipe_path.total_length

    def traverse(self, stream, from_md: float, to_md: float, direction: Literal["up", "down"]):
        """Traverse an arbitrary depth interval [m], returning uncorrected SI conditions."""
        if (direction == "up" and to_md > from_md) or (direction == "down" and to_md < from_md):
            raise PhysicsError(
                f"{self.path}: depth interval {from_md} m -> {to_md} m conflicts with "
                f"direction {direction}"
            )
        return hydraulics.pipe_path_profile(
            self.pipe_path.subpath(from_md, to_md),
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
