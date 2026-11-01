"""Hydrocyclone desander with a quadratic pressure loss and a constant sand removal share."""

from gemini import ops
from gemini.errors import PhysicsError
from gemini.modules._utils.flow import require_forward
from gemini.modules.declarations import Boundary, Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.modules.treatment import _physics
from gemini.physics import fluid, hydraulics
from gemini.types import Fraction, MassConcentration, MassFlow, PressureDifference, Stream


class Desander(Module):
    """Hydrocyclone desander removing a constant share of the produced sand.

    Hydrocyclones separate solids centrifugally; their grade efficiency depends on particle
    size and density relative to the cut size ``d50`` (Svarovsky, 2000, *Solid-Liquid
    Separation*, 4th ed., chapter "Hydrocyclones"). This model lumps the grade-efficiency curve
    over the produced size distribution into one constant ``separation_efficiency``, so it does
    not follow cut-size changes with flow:

    - liquid volume flow ``Q = m_dot * (1 - x_gas) / rho_l``;
    - ``sand_removal_rate = separation_efficiency * sand_concentration * Q``;
    - ``residual_sand_concentration = (1 - separation_efficiency) * sand_concentration``;
    - ``pressure_drop = nominal_pressure_drop * (m_dot / nominal_mass_flow) ** 2``, the quadratic
      law of a fixed-geometry cyclone at constant resistance coefficient (as for ``Filter``).

    ``sand_concentration`` is kg of sand per m3 of liquid at the inlet (1 mg/l = 1 g/m3 =
    1e-3 kg/m3). Streams carry no solids, so the liquid mass flow, temperature and fluid pass
    unchanged and the stream balances close exactly; the removed sand is reported as
    ``sand_removal_rate`` only. Pressure loss (of the order of 1 bar at design flow) and
    efficiency are design specific, so all three design values are required. Valid for forward
    flow with a loss below the inlet pressure; otherwise ``PhysicsError`` is raised.
    """

    def __init__(self):
        """Declare desander design data, ports, sand boundary and outputs."""
        super().__init__()

        # Parameters
        self.separation_efficiency = Parameter(Fraction)
        self.nominal_pressure_drop = Parameter(PressureDifference, ge=0)
        self.nominal_mass_flow = Parameter(MassFlow, gt=0)

        # Inlets
        self.fluid_in = Inlet(Stream, kind="brine")

        # Boundaries
        self.sand_concentration = Boundary(MassConcentration)

        # Outputs
        self.pressure_drop = Output(PressureDifference, soft_sensor=True)
        self.sand_removal_rate = Output(MassFlow, soft_sensor=True)
        self.residual_sand_concentration = Output(MassConcentration)

        # Outlets
        self.fluid_out = Outlet(Stream, kind="brine")
        self.waste_out = Outlet(Stream, kind="waste")

    def forward(self, inlets):
        """Apply the quadratic cyclone pressure loss."""

        # Outlets
        inlet = inlets.fluid_in
        removed, residual = self._sand(inlet)
        drop = self._pressure_drop(inlet)
        outlet = inlet.with_(m_dot=inlet.m_dot - removed, p=inlet.p - drop)
        waste_out = inlet.with_(m_dot=removed)

        # Outputs
        self.pressure_drop = drop
        self.sand_removal_rate = removed
        self.residual_sand_concentration = residual

        outlets = dict(fluid_out=outlet, waste_out=waste_out)
        return outlets

    def _sand(self, inlet):
        """Return the sand removal rate [kg/s] and the residual sand concentration [kg/m3]."""
        properties = inlet.fluid.properties(inlet.p, inlet.T)
        liquid_flow = fluid.liquid_volume_flow(inlet.m_dot, properties.gmf, properties.rho_l)
        return _physics.cyclone_sand(
            self.separation_efficiency, self.sand_concentration, liquid_flow
        )

    def _pressure_drop(self, inlet):
        """Return the cyclone loss [Pa], quadratic in forward mass flow."""
        require_forward(self.path, "fluid_in.m_dot", inlet.m_dot)
        drop = hydraulics.quadratic_pressure_drop(
            self.nominal_pressure_drop, inlet.m_dot, self.nominal_mass_flow
        )
        ops.check(
            drop <= inlet.p,
            PhysicsError,
            "{path}: pressure_drop = {drop} Pa; expected at most fluid_in.p = {pressure} Pa",
            path=self.path,
            drop=drop,
            pressure=inlet.p,
        )
        return drop
