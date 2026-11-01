"""Surface pipeline with wall friction, elevation change and heat exchange with its surroundings."""

from gemini import ops
from gemini.errors import PhysicsError, ValidationError
from gemini.modules._utils.cost import Equipment
from gemini.modules._utils.flow import require_forward
from gemini.modules.declarations import Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.physics import geometry, heat_transfer, hydraulics
from gemini.types import (
    Elevation,
    HeatTransferCoefficient,
    Length,
    Power,
    PressureDifference,
    Speed,
    Stream,
)


class Pipe(Equipment, Module):
    """Surface pipeline carrying a single-phase liquid, with friction, elevation and heat loss.

    Pressure: ``p_out = p_in - friction_pressure_drop - rho g dz`` with ``dz`` the signed
    ``elevation_change`` from inlet to outlet (positive when the outlet is higher). The
    friction drop is Darcy–Weisbach ``f L/D rho v^2/2``: laminar ``f = 64/Re`` (Hagen–Poiseuille)
    up to Re = 2300, Swamee and Jain (1976, Explicit equations for pipe-flow problems, J. Hydraul.
    Div. ASCE 102) from Re = 4000, and in between a linear interpolation in Re of the friction
    drop at the two limits, a continuous bridge without physical claim for the intermittent
    transition regime; all of it in ``hydraulics.pipe_friction_drop``.

    Heat: the fluid exchanges heat with surroundings at the fixed ``ambient_temperature``
    through the overall coefficient ``heat_transfer_coefficient`` referred to the inner wall area
    ``pi d L`` (the convention of the well path model). With constant ``heat_transfer_coefficient``
    and ``cp`` the outlet temperature is the exact exponential profile ``T_out = T_amb + (T_in -
    T_amb) exp(-NTU)``, ``NTU = U pi d L / (m_dot cp)`` (Incropera et al. 2007, Fundamentals of
    Heat and Mass Transfer, 6th ed., Section 8.3, constant external temperature), computed as an
    exchanger with an infinite-capacity ambient (``C_r = 0``). The legacy explicit increment
    ``heat_transfer.pipe_temperature_change`` is its first-order expansion and is not reused
    because it overshoots past ambient when ``NTU > 1``. The heat exchanged leaves as
    ``loss_out`` (fluid warmer than ambient) or enters as ``loss_out`` (negative) (fluid colder), so
    the stream energy audit closes exactly.

    Simplifications: steady state (no fluid or wall heat capacity, no transit time), constant
    fluid properties, uniform ``heat_transfer_coefficient`` and ambient along the pipe, no fittings
    (add their equivalent length to ``length``), kinetic and pressure energy outside the thermal
    model. Validity: single-phase liquid (free gas raises ``PhysicsError``), forward flow
    (reverse flow raises ``PhysicsError``; wire the pipe in the flow direction), relative
    roughness 1e-6 to 1e-2 and Re up to 1e8 (Swamee–Jain range), ``|elevation_change| <=
    length``. Zero flow has no friction or heat exchange and keeps the static head; the stopped
    stream keeps the inlet temperature, which carries no energy.
    """

    equipment_kind = "pipe"

    def __init__(self):
        """Declare pipe geometry, heat transfer, ports and hydraulic and thermal outputs."""
        super().__init__()

        # Parameters
        self.length = Parameter(Length, gt=0, description="Length of the pipe")
        self.inner_diameter = Parameter(Length, gt=0, description="Inner diameter of the pipe")
        self.roughness = Parameter(
            Length,
            description="Absolute roughness of the inner pipe wall",
        )
        self.elevation_change = Parameter(
            Elevation,
            description="Height of the outlet above the inlet (positive when the outlet is higher)",
        )
        self.heat_transfer_coefficient = Parameter(
            HeatTransferCoefficient,
            description="Overall heat transfer coefficient to the surroundings",
        )

        # Inlets
        self.fluid_in = Inlet(Stream)
        self.air_in = Inlet(Stream, kind="air")

        # Outputs
        self.pressure_drop = Output(
            PressureDifference, description="Pressure lost to friction and elevation in the pipe"
        )
        self.velocity = Output(Speed, description="Mean flow velocity in the pipe")

        # Outlets
        self.fluid_out = Outlet(Stream)
        self.loss_out = Outlet(Power, kind="heat")

    def forward(self, inlets):
        """Apply friction, static head and heat exchange to the inlet stream."""

        # Outlets
        inlet = inlets.fluid_in
        self._check(inlet)
        rho = inlet.fluid.properties(inlet.p, inlet.T).rho_l
        static = hydraulics.hydrostatic_dp(rho, self.elevation_change)
        outlet_p = inlet.p - self._friction_drop(inlet) - static
        ops.check(
            outlet_p >= 0,
            PhysicsError,
            "{path}: outlet pressure = {outlet_p} Pa from fluid_in.p = {inlet_p} Pa; "
            "expected the friction and static drops to leave a nonnegative pressure",
            path=self.path,
            outlet_p=outlet_p,
            inlet_p=inlet.p,
        )
        outlet = inlet.with_(T=self._outlet_temperature(inlet, inlets.air_in), p=outlet_p)
        loss_out = heat_transfer.heat_rate(inlet.heat_capacity_rate(), inlet.T - outlet.T)

        # Outputs
        self.pressure_drop = inlet.p - outlet.p
        self.velocity = geometry.mean_velocity(inlet.m_dot, rho, self.inner_diameter)

        outlets = dict(fluid_out=outlet, loss_out=loss_out)
        return outlets

    def capex(self, finance):
        """Return the cost of the pipe from its length."""
        return self.capex_of(finance, self.length)

    def _check(self, inlet):
        """Reject a pipe shorter than its rise, reverse flow and free gas."""
        ops.check(
            ops.abs(self.elevation_change) <= self.length,
            ValidationError,
            "{path}: elevation_change = {elevation_change} m; expected at most "
            "length = {length} m in magnitude",
            path=self.path,
            elevation_change=self.elevation_change,
            length=self.length,
            code="invalid_design",
        )
        require_forward(self.path, "fluid_in.m_dot", inlet.m_dot)
        if inlet.fluid.gas_mass_fraction > 0:
            raise PhysicsError(
                f"{self.path}: inlet.fluid.gas_mass_fraction = "
                f"{inlet.fluid.gas_mass_fraction}; expected 0 (single-phase liquid model)"
            )

    def _friction_drop(self, inlet):
        """Return the friction pressure drop [Pa] for laminar, transitional or turbulent flow."""
        properties = inlet.fluid.properties(inlet.p, inlet.T)
        velocity = geometry.mean_velocity(inlet.m_dot, properties.rho_l, self.inner_diameter)
        return hydraulics.pipe_friction_drop(
            velocity,
            properties.rho_l,
            properties.mu_l,
            self.inner_diameter,
            self.roughness,
            self.length,
        )

    def _outlet_temperature(self, inlet, air):
        """Return the outlet temperature [K] of the exponential ambient-exchange profile."""
        conductance = hydraulics.pipe_conductance(
            self.heat_transfer_coefficient, self.inner_diameter, self.length
        )
        effectiveness = heat_transfer.ambient_effectiveness(conductance, inlet.heat_capacity_rate())
        return heat_transfer.effectiveness_outlet_temperature(inlet.T, effectiveness, air.T)
