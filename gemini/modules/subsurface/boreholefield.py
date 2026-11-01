"""Shallow closed-loop borehole field with a lumped ground temperature."""

from gemini.errors import ValidationError
from gemini.modules._utils.flow import require_forward
from gemini.modules.declarations import Inlet, Outlet, Output, Parameter, State
from gemini.modules.module import Module
from gemini.physics import ground, heat_transfer
from gemini.types import (
    Count,
    Length,
    LinearThermalResistance,
    Power,
    Stream,
    Temperature,
    TemperatureDifference,
    ThermalConductivity,
    VolumetricHeatCapacity,
)


class BoreholeField(Module):
    """Closed-loop borehole field (ground-source heat pump field or BTES), lumped ground.

    The state is the change theta of the mean ground temperature of the field volume
    V = N s**2 H (``borehole_count`` N, ``borehole_spacing`` s, ``borehole_depth`` H) from
    ``undisturbed_ground_temperature`` T_u; ``ground_temperature`` = T_u + theta. The fluid
    exchanges heat with that mean ground temperature through the borehole resistance R_b plus the
    steady-flux resistance R_sf of each borehole's ground cell of equivalent radius
    r_e = s / sqrt(pi) (``ground.steady_flux_resistance``, Hellstrom 1991). With the
    conductance UA = N H / (R_b + R_sf), plug flow along the loop gives the effectiveness
    eps = 1 - exp(-UA / (m_dot cp)), the extraction rate Q = eps m_dot cp (T_g - T_in) and
    fluid_out_T = T_in + eps (T_g - T_in); ``fluid_mean_temperature`` is the arithmetic mean of
    inlet
    and outlet, the usual design convention. A positive Q is heat taken from the ground
    (``loss_out`` negative), a negative Q heat rejected into it (``loss_out``; the ground is the
    plant's environment), so the stream audit closes.

    The field volume, of heat capacity C = (rho c)_g V, also exchanges heat with the
    undisturbed ground through the steady conductance of a vertical cylinder of depth H and
    plan diameter D = 2 sqrt(N s**2 / pi) below an isothermal surface,
    UA_s = k 2 pi H / ln(4 H / D) (Incropera et al., table 4.1). The step solves
    C dtheta/dt = -Q - UA_s theta exactly for a constant inlet over ``dt``:
    theta(dt) = theta_eq + (theta - theta_eq) exp(-(K + UA_s) dt / C) with K = eps m_dot cp
    and theta_eq = K (T_in - T_u) / (K + UA_s).

    Simplification against g-functions (Eskilson 1987, Thermal analysis of heat extraction
    boreholes, Lund University): the lumped model keeps the field's long-term energy
    balance, ground depletion and recovery, but not the short-term borehole response (hours
    to about r_e**2 / (4 alpha), when the steady-flux regime sets in), nor the thermal
    interaction pattern within the field, nor the logarithmic long-term g-function growth.
    It suits monthly to seasonal behaviour; peak-hour fluid temperatures are optimistic.
    Constant properties, uniform ground, no groundwater flow and no axial heat flow in the
    ground are assumed. Zero flow exchanges no heat and returns the inlet unchanged.

    NOTE(refactor): written with ops, but a graph break while the graph has no ``scan``: the
    ground temperature change is a state.
    """

    def __init__(self):
        """Declare field geometry, ground properties and the ground temperature state."""
        super().__init__()

        # Parameters
        self.borehole_count = Parameter(Count)
        self.borehole_depth = Parameter(Length, gt=0)
        self.borehole_radius = Parameter(Length, gt=0)
        self.borehole_spacing = Parameter(Length, gt=0)
        self.borehole_resistance = Parameter(LinearThermalResistance, calibratable=True)
        self.ground_conductivity = Parameter(ThermalConductivity, calibratable=True)
        self.ground_volumetric_heat_capacity = Parameter(VolumetricHeatCapacity)
        self.undisturbed_ground_temperature = Parameter(Temperature)

        # Inlets
        self.fluid_in = Inlet(Stream, kind="hot_water")

        # States
        self.ground_temperature_change = State(TemperatureDifference, default=0)

        # Outputs
        self.fluid_mean_temperature = Output(Temperature)
        self.ground_temperature = Output(Temperature)

        # Outlets
        self.fluid_out = Outlet(Stream, kind="hot_water")
        self.loss_out = Outlet(Power, kind="heat")

    def forward(self, inlets):
        """Exchange heat between the loop fluid and the start-of-step ground temperature."""

        # Outlets
        inlet = inlets.fluid_in
        capacity_rate = self._capacity_rate(inlet)
        rate = self._extraction_rate(inlet)
        fluid_out_T = inlet.T + heat_transfer.temperature_change(rate, capacity_rate)
        outlet = inlet.with_(T=fluid_out_T)

        # Outputs
        self.fluid_mean_temperature = heat_transfer.mean_temperature(inlet.T, outlet.T)
        self.ground_temperature = self._ground_temperature()

        outlets = dict(fluid_out=outlet, loss_out=-rate)
        return outlets

    def _advance_states(self, inlets, outlets, dt):
        inlet = inlets.fluid_in
        change = ground.borehole_field_temperature_change(
            self.ground_temperature_change,
            self._effective_conductance(inlet),
            self._surroundings_conductance(),
            inlet.T,
            self.undisturbed_ground_temperature,
            dt,
            self._ground_heat_capacity(),
        )
        return {"ground_temperature_change": change}

    @property
    def _rejection(self):
        """Return the message prefix of a field geometry outside the range of its relations."""
        return f"{self.path}: field geometry rejected: "

    def _extraction_rate(self, inlet):
        """Return the heat [W] the loop draws from the ground at the start of the step."""
        return heat_transfer.heat_rate(
            self._effective_conductance(inlet), self._ground_temperature() - inlet.T
        )

    def _ground_temperature(self):
        """Return the mean field ground temperature [K] at the start of the step."""
        return self.undisturbed_ground_temperature + self.ground_temperature_change

    def _effective_conductance(self, inlet):
        """Return K = eps m_dot cp [W/K], the inlet-to-ground conductance of the loop."""
        return ground.borehole_loop_conductance(
            self._capacity_rate(inlet),
            self.borehole_count,
            self.borehole_depth,
            self.borehole_radius,
            self.borehole_spacing,
            self.ground_conductivity,
            self.borehole_resistance,
            error=ValidationError,
            code="invalid_design",
            context=self._rejection,
        )

    def _surroundings_conductance(self):
        """Return the conductance [W/K] between the field volume and the undisturbed ground."""
        return ground.borehole_field_surroundings_conductance(
            self.borehole_count,
            self.borehole_spacing,
            self.borehole_depth,
            self.ground_conductivity,
            error=ValidationError,
            code="invalid_design",
            context=self._rejection,
        )

    def _ground_heat_capacity(self):
        """Return the heat capacity [J/K] of the lumped field volume."""
        return ground.borehole_field_capacity(
            self.ground_volumetric_heat_capacity,
            self.borehole_count,
            self.borehole_spacing,
            self.borehole_depth,
        )

    def _capacity_rate(self, inlet):
        """Return m_dot cp [W/K] of the loop flow; reverse flow is outside the model."""
        require_forward(self.path, "fluid_in.m_dot", inlet.m_dot)
        return inlet.heat_capacity_rate()
