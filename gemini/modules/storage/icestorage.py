"""Lumped ice-on-coil or encapsulated ice store on one glycol circuit."""

from gemini import ops, units
from gemini.errors import ValidationError
from gemini.modules._utils.flow import require_forward
from gemini.modules.declarations import Inlet, Outlet, Output, Parameter, State
from gemini.modules.module import Module
from gemini.modules.storage import _physics
from gemini.physics import heat_transfer
from gemini.types import (
    Energy,
    Fraction,
    HeatAccumulation,
    Mass,
    SpecificEnthalpy,
    SpecificHeat,
    Stream,
    Temperature,
    ThermalConductance,
)


class IceStorage(Module):
    """Lumped ice store for cooling: a glycol coil freezes or melts a fixed mass of water.

    The store holds ``water_mass`` M of water at one uniform temperature T, of which the
    state ``ice_fraction`` x is frozen. The state ``temperature`` is the store temperature: the
    freezing temperature T_f while partly frozen (0 < x < 1), above it only as all liquid
    (x = 0, sensible heat with ``water_specific_heat``) and below it only as all ice (x = 1,
    sensible heat with ``ice_specific_heat``). Other combinations raise ``ValidationError``.

    The coil is a heat exchanger against a store at uniform temperature (capacity ratio zero),
    so with ``C = m_dot * cp`` of the glycol its effectiveness is ``e = 1 - exp(-UA / C)``
    (Incropera et al., *Fundamentals of Heat and Mass Transfer*, effectiveness-NTU method). The
    heat flow from the glycol into the store is ``duty = e * C * (T_in - T)`` and the glycol
    leaves at ``fluid_out_T = T_in - e * (T_in - T)``. A glycol inlet below T_f charges the store
    (negative duty: water freezes, then the ice subcools), one above T_f discharges it (positive
    duty: the store cools the glycol, the ice melts, then the water warms).

    ``_advance_states`` integrates the enthalpy balance exactly and piecewise over ``dt`` for an
    inlet held constant during the step: in the latent segment T = T_f and the duty is constant,
    so x changes linearly by ``-duty * t / (M * L)``; in a sensible segment T relaxes towards
    ``T_in`` with the time constant ``M * c / (e * C)``. A step moves to the next segment when
    the store becomes full (x = 1) or empty (x = 0), or reaches T_f, so it can cross at most
    three segments. Outlets and outputs use the start-of-step state.

    ``stored_cold = M * L * x`` is the latent cold available. The store is perfectly insulated
    and the coil carries the glycol in a closed circuit, so ``mass_balance`` closes.
    ``heat_accumulation`` equals ``duty``, the rate of increase of the store's internal energy
    at the start of the step (negative while charging with cold); ``energy_balance`` counts it as
    the signed storage outflow, so the store is first-law closed.

    Defaults: ``latent_heat`` 333.55 kJ/kg is the conventional latent heat of fusion of ice at
    0 degC and 101.325 kPa; IAPWS R10-06 (Feistel and Wagner 2006, *A new equation of state for
    H2O ice Ih*) gives 333.44 kJ/kg at the triple point, 0.03 % lower. ``freezing_temperature``
    273.15 K is the normal melting point. ``water_specific_heat`` 4219.9 J/kg/K is saturated
    liquid water at 0.01 degC (IAPWS-95, Wagner and Pruss 2002) and ``ice_specific_heat``
    2096.8 J/kg/K is ice Ih at the triple point (IAPWS R10-06).

    Simplifications and validity: one lumped store temperature, constant coil UA (in a real
    ice-on-coil store UA falls as the ice layer thickens and depends on the glycol flow regime;
    ASHRAE Handbook, HVAC Applications, chapter Thermal Storage), constant properties, no
    supercooling or nucleation delay, no ambient heat gain and no pressure loss. Suitable for
    hourly or 15-minute dispatch studies of the store's state of charge, not for coil design.

    NOTE(refactor): the ice fraction and the temperature are states, so the module is a graph
    break until ``scan`` exists; its arithmetic is written with ops all the same, and the segment
    loop of ``_physics.ice_advance`` runs its fixed ``_physics.MAX_SEGMENTS`` passes, a finished
    pass keeping its state. The coil follows ``heat_transfer.ambient_effectiveness`` and
    ``_physics.circuit_conductance``; the segments are ``_physics.ice_step``.
    """

    def __init__(self):
        """Declare store design data, the glycol circuit, the phase state and its energies."""
        super().__init__()

        # Parameters
        self.water_mass = Parameter(Mass, gt=0)
        self.thermal_conductance = Parameter(ThermalConductance, gt=0)
        self.latent_heat = Parameter(SpecificEnthalpy, default=_physics.DEFAULT_LATENT_HEAT, gt=0)
        self.freezing_temperature = Parameter(
            Temperature, default=_physics.DEFAULT_FREEZING_TEMPERATURE
        )
        self.water_specific_heat = Parameter(
            SpecificHeat, default=_physics.DEFAULT_WATER_HEAT_CAPACITY
        )
        self.ice_specific_heat = Parameter(SpecificHeat, default=_physics.DEFAULT_ICE_HEAT_CAPACITY)

        # Inlets
        self.fluid_in = Inlet(Stream, kind="chilled_water")

        # States
        self.ice_fraction = State(Fraction, default=0)
        self.temperature = State(Temperature, default=units.ZERO_CELSIUS)

        # Outputs
        self.stored_cold = Output(Energy)
        self.heat_accumulation = Output(HeatAccumulation)
        self.is_full = Output(bool)
        self.is_empty = Output(bool)

        # Outlets
        self.fluid_out = Outlet(Stream, kind="chilled_water")

    def forward(self, inlets):
        """Return the glycol after exchanging heat with the start-of-step store."""

        # Outlets
        inlet = inlets.fluid_in
        effectiveness = self._effectiveness(inlet)
        outlet = inlet.with_(
            T=heat_transfer.effectiveness_outlet_temperature(
                inlet.T, effectiveness, self.temperature
            )
        )

        # Outputs
        self.stored_cold = _physics.ice_stored_cold(
            self.water_mass, self.latent_heat, self.ice_fraction
        )
        inlet, outlet = inlets.fluid_in, outlet
        self.heat_accumulation = heat_transfer.heat_rate(
            inlet.heat_capacity_rate(), inlet.T - outlet.T
        )
        self.is_full = self.ice_fraction >= 1
        self.is_empty = self.ice_fraction <= 0

        outlets = dict(fluid_out=outlet)
        return outlets

    def _advance_states(self, inlets, outlets, dt):
        inlet = inlets.fluid_in
        fraction, temperature = _physics.ice_advance(
            self.ice_fraction,
            self.temperature,
            dt,
            inlet.T,
            self._conductance(inlet),
            self.water_mass,
            self.latent_heat,
            self.freezing_temperature,
            self.water_specific_heat,
            self.ice_specific_heat,
        )
        return {"ice_fraction": fraction, "temperature": temperature}

    def _rate(self, inlet):
        """Return the glycol capacity rate m_dot * cp [W/K]; reject reverse flow."""
        require_forward(self.path, "fluid_in.m_dot", inlet.m_dot)
        return inlet.heat_capacity_rate()

    def _effectiveness(self, inlet):
        """Return the coil effectiveness 1 - exp(-UA / C) [-] after checking the store state."""
        self._check_state()
        rate = self._rate(inlet)
        return heat_transfer.ambient_effectiveness(self.thermal_conductance, rate)

    def _conductance(self, inlet):
        """Return the coil conductance e * m_dot * cp [W/K]."""
        return _physics.circuit_conductance(self._effectiveness(inlet), self._rate(inlet))

    def _check_state(self):
        """Require the store temperature to match its phase (see the class docstring)."""
        fraction, temperature = self.ice_fraction, self.temperature
        freezing = self.freezing_temperature
        consistent = ops.logical_or(
            ops.logical_or(
                temperature == freezing,
                ops.logical_and(fraction == 0, temperature > freezing),
            ),
            ops.logical_and(fraction == 1, temperature < freezing),
        )
        ops.check(
            consistent,
            ValidationError,
            "{path}: temperature = {temperature} K with ice_fraction = {fraction}; "
            "expected {freezing} K while partly frozen, above it only with no ice and "
            "below it only when fully frozen",
            path=self.path,
            temperature=temperature,
            fraction=fraction,
            freezing=freezing,
            code="invalid_design",
        )
