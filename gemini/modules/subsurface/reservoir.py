"""Production and injection reservoir modules for a geothermal doublet."""

from typing import Literal

from gemini import ops
from gemini.errors import PhysicsError, ValidationError
from gemini.modules.declarations import Control, Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.physics import diagnostics
from gemini.physics import fluid as fluid_physics
from gemini.physics import hydraulics
from gemini.types import (
    Dimensionless,
    Fraction,
    Health,
    Length,
    MassFlow,
    Permeability,
    Pressure,
    PressureDifference,
    ProductivityIndex,
    Stream,
    Temperature,
    VolumeFlow,
)
from gemini.types.results import NOT_ASSESSED


class _Reservoir(Module):
    """Common reservoir parameters and measurement helpers."""

    abstract = True

    def __init__(self, role):
        super().__init__()

        # Parameters
        self.role = Parameter(
            Literal["production", "injection"],
            default=role,
            description="Whether the reservoir supplies production or receives injection",
        )
        self.pressure = Parameter(
            Pressure, calibratable=True, description="Static reservoir pressure"
        )
        self.temperature = Parameter(Temperature, description="Undisturbed reservoir temperature")
        self.permeability = Parameter(Permeability, description="Permeability of the aquifer rock")
        self.aquifer_thickness = Parameter(Length, gt=0, description="Thickness of the aquifer")
        self.drainage_radius = Parameter(
            Length, structural=True, description="Radius of the drainage area around the well"
        )
        self.top_depth = Parameter(Length, description="Depth of the top of the aquifer")
        self.productivity_index = Parameter(
            ProductivityIndex | None,
            default=None,
            calibratable=True,
            description="Production rate per unit of drawdown; empty derives it from the aquifer",
        )
        self.injectivity_index = Parameter(
            ProductivityIndex | None,
            default=None,
            calibratable=True,
            description=(
                "Injection rate per unit of overpressure; empty derives it from the aquifer"
            ),
        )
        self.skin = Parameter(
            Dimensionless,
            calibratable=True,
            description="Dimensionless skin factor of the near-well zone",
        )
        self.wellbore_radius = Parameter(
            Length, gt=0, description="Radius of the wellbore at the aquifer"
        )
        self.decline_threshold = Parameter(
            Fraction | None,
            default=None,
            gt=0,
            le=1,
            description=(
                "Relative productivity decline at which the alarm is raised; empty switches the "
                "health check off"
            ),
        )

        # Outputs
        self.bottomhole_pressure = Output(
            Pressure, soft_sensor=True, description="Flowing pressure at the bottom of the well"
        )
        self.drawdown = Output(
            PressureDifference,
            description="Pressure below the static reservoir pressure at the bottom of the well",
        )
        self.overpressure = Output(
            PressureDifference,
            description="Pressure above the static reservoir pressure at the bottom of the well",
        )
        self.flow_pressure_drop = Output(
            PressureDifference | None, description="Pressure drop of the radial flow in the aquifer"
        )
        self.skin_pressure_drop = Output(
            PressureDifference | None, description="Pressure drop across the skin zone"
        )
        self.hydrostatic_pressure_drop = Output(
            PressureDifference,
            description="Pressure change caused by the weight of the fluid column",
        )
        self.radial_bottomhole_pressure = Output(
            Pressure | None, description="Bottomhole pressure from the radial flow equation"
        )

    def _calculate_outputs(self, flow, p_bh):
        properties = self.fluid.properties(self.pressure, self.temperature)
        if self.drainage_radius == 0:
            flow_pressure_drop = skin_pressure_drop = radial = None
        else:
            flow_pressure_drop, skin_pressure_drop = hydraulics.radial_pressure_drops(
                flow,
                properties.mu_l,
                self.permeability,
                self.aquifer_thickness,
                self.drainage_radius,
                self.wellbore_radius,
                self.skin,
            )
            radial = self.pressure + flow_pressure_drop + skin_pressure_drop
        return {
            "bottomhole_pressure": p_bh,
            "drawdown": self.pressure - p_bh if self.role == "production" else 0,
            "overpressure": p_bh - self.pressure if self.role == "injection" else 0,
            "flow_pressure_drop": flow_pressure_drop,
            "skin_pressure_drop": skin_pressure_drop,
            "hydrostatic_pressure_drop": hydraulics.hydrostatic_dp(
                properties.rho_l, self.top_depth
            ),
            "radial_bottomhole_pressure": radial,
        }

    def _index_from_measurement(self, index, word, flow, p_bh):
        ops.check(
            p_bh != self.pressure,
            PhysicsError,
            "{path}: bottomhole pressure = reservoir pressure = {p_bh} Pa; "
            "{word} needs a pressure differential",
            path=self.path,
            p_bh=p_bh,
            word=word,
        )
        return index(flow, self.pressure, p_bh)

    @ops.physics
    def injectivity_from_measurements(self, flow, p_bh):
        """Return injectivity [m3/s/Pa] from one measurement."""
        return self._index_from_measurement(hydraulics.injectivity_index, "injectivity", flow, p_bh)

    @ops.physics
    def productivity_from_measurements(self, flow, p_bh):
        """Return productivity [m3/s/Pa] from one measurement."""
        return self._index_from_measurement(
            hydraulics.productivity_index, "productivity", flow, p_bh
        )

    @ops.physics
    def health(self, result, measured):
        """Alarm on declining measured PI or II relative to design.

        Returns ``None`` (not assessed) without both measurements or without a nonzero design
        index. Where the measured bottomhole pressure equals the reservoir pressure the row is
        not assessed: ``assessed`` is false, the score is one, no alarm, the message is
        ``NOT_ASSESSED`` and the metrics are NaN, a row without metrics in the results.
        """
        production = self.role == "production"
        nominal = self.productivity_index if production else self.injectivity_index
        if not {"flow", "bottomhole_pressure"} <= measured.keys() or not nominal:
            return None
        if self.decline_threshold is None:
            return None
        pressure = measured["bottomhole_pressure"]
        assessed = pressure != self.pressure
        index = hydraulics.productivity_index if production else hydraulics.injectivity_index
        actual = ops.where(assessed, index(measured["flow"], self.pressure, pressure), float("nan"))
        ratio = diagnostics.performance_ratio(actual, nominal)
        return Health(
            assessed=assessed,
            score=ops.where(assessed, diagnostics.bounded_score(ratio), 1.0),
            alarm=ops.logical_and(assessed, diagnostics.below_limit(ratio, self.decline_threshold)),
            message=ops.where(
                assessed,
                ("Productivity" if production else "Injectivity") + " index comparison",
                NOT_ASSESSED,
            ),
            metrics={"index": actual, "ratio": ratio},
        )


class ProductionReservoir(_Reservoir):
    """Aquifer supplying a production-well sandface stream."""

    def __init__(self):
        """Declare a production reservoir."""
        super().__init__("production")

        # Controls
        self.production_rate = Control(
            MassFlow, ge=0, description="Mass flow produced from the aquifer"
        )

        # Outputs
        self.liquid_flow = Output(
            VolumeFlow, description="Liquid volume flow produced from or injected into the aquifer"
        )

        # Outlets
        self.sandface_out = Outlet(Stream, kind="brine")

    def forward(self, inlets):
        """Apply the linear production IPR and emit the sandface stream."""

        # Outlets
        sandface = self.sandface_stream(self.production_rate)

        # Outputs
        flow = sandface.volumetric_flow()
        for name, value in self._calculate_outputs(flow, sandface.p).items():
            setattr(self, name, value)
        properties = sandface.fluid.properties(sandface.p, sandface.T)
        self.liquid_flow = fluid_physics.liquid_volume_flow(
            sandface.m_dot, properties.gmf, properties.rho_l
        )

        outlets = dict(sandface_out=sandface)
        return outlets

    def sandface_stream(self, production_rate):
        """Return the sandface stream [SI] the linear IPR delivers at a production rate [kg/s].

        ``p_bh = pressure - Q / productivity_index`` with the volume flow Q at reservoir
        conditions. ``forward`` uses it for the commanded rate; ``gm.analysis.nodal`` uses it for
        trial rates without a call.
        """
        if self.productivity_index is None:
            raise ValidationError(
                f"{self.path}: productivity_index is required", code="invalid_design"
            )
        flow = fluid_physics.volume_flow(
            production_rate, self.fluid.properties(self.pressure, self.temperature).rho_l
        )
        p_bh = hydraulics.productivity_pressure(self.pressure, flow, self.productivity_index)
        return Stream(m_dot=production_rate, T=self.temperature, p=p_bh, fluid=self.fluid)


class InjectionReservoir(_Reservoir):
    """Aquifer receiving the injection-well sandface stream."""

    def __init__(self):
        """Declare an injection reservoir."""
        super().__init__("injection")

        # Inlets
        self.sandface_in = Inlet(Stream, kind="brine")

        # Outputs
        self.liquid_flow = Output(
            VolumeFlow, description="Liquid volume flow produced from or injected into the aquifer"
        )

    def forward(self, inlets):
        """Receive the sandface stream; the aquifer has no outlet."""

        if self.injectivity_index is None:
            raise ValidationError(
                f"{self.path}: injectivity_index is required", code="invalid_design"
            )
        # Outputs
        sandface = inlets.sandface_in
        flow = fluid_physics.volume_flow(
            ops.abs(sandface.m_dot), self.fluid.properties(sandface.p, sandface.T).rho_l
        )
        for name, value in self._calculate_outputs(flow, self.required_pressure(sandface)).items():
            setattr(self, name, value)
        properties = sandface.fluid.properties(sandface.p, sandface.T)
        self.liquid_flow = fluid_physics.liquid_volume_flow(
            ops.abs(sandface.m_dot), properties.gmf, properties.rho_l
        )

        outlets = dict()
        return outlets

    def required_pressure(self, sandface):
        """Return the bottomhole pressure [Pa] the linear injectivity needs for a sandface stream.

        ``p_bh = pressure + Q / injectivity_index`` with Q the absolute volume flow of the
        stream. The aquifer accepts any arriving stream; a constraint of a plant matches the
        injection well's bottom pressure to this value, through ``bottomhole_pressure``.
        """
        if self.injectivity_index is None:
            raise ValidationError(
                f"{self.path}: injectivity_index is required", code="invalid_design"
            )
        flow = fluid_physics.volume_flow(
            ops.abs(sandface.m_dot), self.fluid.properties(sandface.p, sandface.T).rho_l
        )
        return hydraulics.injectivity_pressure(self.pressure, flow, self.injectivity_index)
