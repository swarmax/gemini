"""Deep closed-loop downhole heat exchanger in a linear geothermal gradient."""

from gemini import ops
from gemini.errors import ValidationError
from gemini.modules._utils.flow import require_forward
from gemini.modules.declarations import Inlet, Outlet, Parameter
from gemini.modules.module import Module
from gemini.physics import ground, heat_transfer
from gemini.types import (
    Duration,
    Length,
    LinearThermalResistance,
    Power,
    Stream,
    Temperature,
    TemperatureGradient,
    ThermalConductivity,
    ThermalDiffusivity,
)


class DownholeHeatExchanger(Module):
    """Deep coaxial closed-loop heat exchanger with Ramey's quasi-steady rock resistance.

    The circuit fluid flows down the annulus to ``depth``, exchanging heat with rock whose
    undisturbed temperature rises linearly from ``surface_temperature`` with
    ``geothermal_gradient``, and returns through an insulated centre pipe. Per unit length the
    fluid sees the resistance R = R_b + f(t) / (2 pi k): the ``borehole_resistance`` R_b
    (fluid to borehole wall) plus the transient rock resistance with Ramey's time function
    f(t) = ln(2 sqrt(alpha t) / r_b) - gamma / 2 evaluated at the quasi-steady
    ``operating_time`` t (Ramey 1962, Wellbore heat transmission, J. Petroleum Technology
    14(4), 427-435; ``ground.ramey_time_function``). The steady energy balance
    m_dot cp dT/dz = (T_rock(z) - T) / R gives Ramey's exact profile with the relaxation
    length A = m_dot cp R (``ground.ramey_fluid_temperature``), and the fluid leaves at the
    bottom-hole temperature: fluid_out_T = T(depth). ``heat_extraction_rate`` is
    m_dot cp (fluid_out.T - T_in); heat taken from the rock is a negative ``loss_out``, heat given
    to it (an inlet warmer than the rock) a positive one, so the stream audit closes.

    Assumptions: steady state at a fixed operating time (no load history; the rock
    resistance applies a constant, uniform heat flux along the depth); a perfectly insulated
    return pipe, so no heat exchange between the up- and down-flowing fluid (a U-tube or a
    poorly insulated coaxial pipe delivers less); constant fluid and rock properties; no
    friction heating or pressure work; mass and pressure pass unchanged (hydraulics belong to
    a pipe or well module). Valid for alpha t / r_b**2 >= 25 (``ground.MIN_RAMEY_FOURIER``),
    typically after a few days of operation. Zero flow exchanges no heat and returns the
    inlet unchanged.
    """

    def __init__(self):
        """Declare the well geometry, the geothermal profile and the rock properties."""
        super().__init__()

        # Parameters
        self.borehole_depth = Parameter(Length, gt=0)
        self.surface_temperature = Parameter(Temperature)
        self.geothermal_gradient = Parameter(TemperatureGradient)
        self.ground_conductivity = Parameter(ThermalConductivity, calibratable=True)
        self.ground_diffusivity = Parameter(ThermalDiffusivity)
        self.borehole_radius = Parameter(Length, gt=0)
        self.borehole_resistance = Parameter(LinearThermalResistance, calibratable=True)
        self.operating_time = Parameter(Duration, gt=0)

        # Inlets
        self.fluid_in = Inlet(Stream, kind="hot_water")

        # Outlets
        self.fluid_out = Outlet(Stream, kind="hot_water")
        self.loss_out = Outlet(Power, kind="heat")

    def forward(self, inlets):
        """Return the fluid at the temperature it reaches at the bottom of the annulus."""

        # Outlets
        inlet = inlets.fluid_in
        outlet = inlet.with_(T=self._outlet_temperature(inlet))
        loss_out = heat_transfer.heat_rate(inlet.heat_capacity_rate(), inlet.T - outlet.T)

        outlets = dict(fluid_out=outlet, loss_out=loss_out)
        return outlets

    def _outlet_temperature(self, inlet):
        """Return the bottom-hole fluid temperature [K] from Ramey's profile.

        Zero flow returns the inlet temperature. Both results are always evaluated: at zero flow
        the profile's check of the relaxation length fails and ``where`` drops its error.
        """
        require_forward(self.path, "fluid_in.m_dot", inlet.m_dot)
        relaxation = ground.ramey_relaxation_length(
            inlet.heat_capacity_rate(), self.borehole_resistance, self._rock_resistance()
        )
        profile = ground.ramey_fluid_temperature(
            inlet.T,
            self.surface_temperature,
            self.geothermal_gradient,
            self.borehole_depth,
            relaxation,
        )
        return ops.where(inlet.m_dot == 0, inlet.T, profile)

    def _rock_resistance(self):
        """Return the transient rock resistance f(t) / (2 pi k) [m K/W].

        An operating time that is too early for Ramey's asymptote is a configuration error,
        except at zero flow, whose profile never uses the resistance.
        """
        return ground.ramey_rock_resistance(
            self.operating_time,
            self.ground_diffusivity,
            self.borehole_radius,
            self.ground_conductivity,
            error=ValidationError,
            code="invalid_design",
            context=f"{self.path}: operating_time rejected: ",
        )
