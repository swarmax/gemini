"""Injection well from the wellhead down to the sandface."""

from gemini import ops
from gemini.modules.declarations import Inlet, Outlet, Output
from gemini.modules.wells.well import _Well
from gemini.physics import fluid, heat_transfer, hydraulics
from gemini.types import Power, Pressure, PressureDifference, Stream, Temperature


class InjectionWell(_Well):
    """Injection-well pressure and temperature profile with integrity checks.

    NOTE(refactor): legacy injection DPDT uses negative flow; the traversal retains that sign
    convention internally while the ports preserve the incoming mass-flow sign.

    NOTE(refactor): the ``section_pressure`` and ``section_temperature`` list outputs are vector
    outputs of the graph, one item per section.
    """

    flow_direction = "down"

    def __init__(self):
        """Declare injection-well geometry, inlet and outputs."""
        super().__init__()

        # Inlets
        self.wellhead_in = Inlet(Stream, kind="brine")

        # Outputs
        self.friction_pressure_drop = Output(
            PressureDifference, description="Pressure drop caused by friction along the well"
        )
        self.gravity_pressure_drop = Output(
            PressureDifference,
            description="Pressure change caused by the weight of the fluid column",
        )
        self.section_pressure = Output(
            list[Pressure], description="Pressure at each section of the well"
        )
        self.section_temperature = Output(
            list[Temperature], description="Temperature at each section of the well"
        )

        # Outlets
        self.bottom_out = Outlet(Stream, kind="brine")
        self.loss_out = Outlet(Power, kind="heat")

    def forward(self, inlets):
        """Traverse the injection path with the legacy negative flow convention."""

        # Outlets
        wellhead = inlets.wellhead_in
        stream = self._traversal_stream(wellhead)
        result = self.traverse(stream, 0, self.pipe_path.total_length, "down")
        slope, offset = self.correction_factors

        bottom = stream.with_(
            p=hydraulics.affine_correction(result.p_out, slope, offset),
            T=result.T_out,
            m_dot=wellhead.m_dot,
        )

        # Outputs
        self.friction_pressure_drop = result.friction_pressure_drop
        self.gravity_pressure_drop = result.gravity_pressure_drop
        self.section_pressure = result.section_pressure
        self.section_temperature = result.section_temperature

        outlets = dict(bottom_out=bottom, loss_out=self._loss(stream, bottom))
        return outlets

    def _loss(self, stream, bottom):
        """Return the heat [W] the well gives to the rock between its two ends."""
        capacity_rate = fluid.heat_capacity_rate(
            bottom.m_dot, stream.fluid.properties(stream.p, stream.T).cp_l
        )
        return heat_transfer.heat_rate(capacity_rate, stream.T - bottom.T)

    def _traversal_stream(self, stream):
        """Return the stream with the negative flow the legacy injection DPDT expects."""
        return stream.with_(m_dot=-ops.abs(stream.m_dot))
