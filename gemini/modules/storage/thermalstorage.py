"""Fully mixed hot or chilled water storage tank with a charge and a discharge circuit."""

from typing import Literal

from gemini import ops
from gemini.errors import PhysicsError
from gemini.modules._utils.cost import Equipment
from gemini.modules.declarations import Inlet, Outlet, Output, Parameter, State
from gemini.modules.module import Module
from gemini.modules.storage import _physics
from gemini.physics import heat_transfer
from gemini.types import (
    Energy,
    Fraction,
    HeatAccumulation,
    Power,
    Stream,
    Temperature,
    ThermalConductance,
    Volume,
)


class ThermalStorage(Equipment, Module):
    """Fully mixed (lumped) hot or chilled water tank with charge and discharge circuits.

    The tank content is ``module.fluid`` at one uniform temperature, the state ``temperature``.
    Each circuit exchanges heat with the tank through a constant effectiveness ``e``
    (``charge_effectiveness``, ``discharge_effectiveness``); the default ``e = 1`` is a direct
    connection, where the circuit leaves at the tank temperature. With ``C_i = m_dot_i * cp_i``
    the heat flows into the tank are ``Q_i = e_i * C_i * (T_i_in - T)`` and the circuit leaves
    at ``T_i_out = T_i_in - e_i * (T_i_in - T)``; the ambient exchange is
    ``Q_amb = UA * (T - T_ambient)``. The tank balance (Duffie and Beckman 2013, *Solar
    Engineering of Thermal Processes*, 4th ed., section 8.3, fully mixed storage) is

        rho * cp * V * dT/dt = Q_charge + Q_discharge - Q_amb.

    ``_advance_states`` integrates it with its exact exponential solution over ``dt`` for inlets
    held constant during the step: with ``b = e_c C_c + e_d C_d + UA`` and the equilibrium
    ``T_eq = (e_c C_c T_c + e_d C_d T_d + UA T_ambient) / b``,
    ``T(dt) = T_eq + (T(0) - T_eq) * exp(-b dt / (rho cp V))``; it is unconditionally stable.
    Outlets and outputs use the start-of-step temperature.

    ``service`` sets the sign of the reported energies: a ``"hot"`` tank stores heat, so
    ``stored_energy = rho cp V (T - T_ref)``, ``charge_duty = Q_charge`` and ``discharge_duty =
    -Q_discharge``; a ``"chilled"`` tank stores cold, so every sign flips and ``stored_energy =
    rho cp V (T_ref - T)``. A negative duty means the circuit works against the service (for
    example charge water colder than a hot tank). ``loss_out`` is ``Q_amb``, negative for a chilled
    tank in a warm room.

    ``heat_accumulation`` is the rate of increase of the tank's sensible heat
    ``rho cp V dT/dt`` at the start of the step; ``energy_balance`` counts it as the signed
    storage outflow, so the tank is first-law closed. Each circuit keeps its mass flow, pressure
    and fluid (constant tank volume, no pressure loss), so ``mass_balance`` closes.

    Assumptions and validity: single-phase liquid below boiling, no thermal stratification
    (a stratified tank delivers hotter discharge water than this model), constant fluid
    properties at the start-of-step temperature, constant effectiveness independent of flow,
    and inlet temperatures constant over a step (use steps short against the tank time
    constant ``rho cp V / b`` when the inlets vary).

    NOTE(refactor): the tank temperature is a state, so the module is a graph break until
    ``scan`` exists; its arithmetic is written with ops all the same.
    """

    equipment_kind = "thermal_storage"

    def __init__(self):
        """Declare tank design data, circuits, the tank temperature and its energies."""
        super().__init__()

        # Parameters
        self.service = Parameter(Literal["hot", "chilled"])
        self.volume = Parameter(Volume, gt=0)
        self.heat_loss_conductance = Parameter(ThermalConductance)
        self.reference_temperature = Parameter(Temperature)
        self.charge_effectiveness = Parameter(Fraction, default=1)
        self.discharge_effectiveness = Parameter(Fraction, default=1)

        # Inlets
        self.charge_in = Inlet(Stream, kind="hot_water")
        self.discharge_in = Inlet(Stream, kind="hot_water")
        self.air_in = Inlet(Stream, kind="air")

        # States
        self.temperature = State(Temperature, default=_physics.DEFAULT_TANK_TEMPERATURE)

        # Outputs
        self.tank_temperature = Output(Temperature)
        self.stored_energy = Output(Energy)
        self.heat_accumulation = Output(HeatAccumulation)

        # Outlets
        self.charge_out = Outlet(Stream, kind="hot_water")
        self.discharge_out = Outlet(Stream, kind="hot_water")
        self.loss_out = Outlet(Power, kind="heat")

    def forward(self, inlets):
        """Return both circuits after exchanging heat with the start-of-step tank."""

        # Outlets
        charge_in, discharge_in = inlets.charge_in, inlets.discharge_in
        charge_T = self._outlet_temperature(charge_in, self.charge_effectiveness)
        fluid_out_T = self._outlet_temperature(discharge_in, self.discharge_effectiveness)
        charge_out = charge_in.with_(T=charge_T)
        discharge_out = discharge_in.with_(T=fluid_out_T)

        loss_out = heat_transfer.heat_rate(
            self.heat_loss_conductance, self.temperature - inlets.air_in.T
        )

        # Outputs
        charge = self._circuit_heat(charge_in, self.charge_effectiveness)
        discharge = self._circuit_heat(discharge_in, self.discharge_effectiveness)
        reports = _physics.tank_service_report(
            self.service == "hot",
            self._capacity(charge_in),
            self.temperature,
            self.reference_temperature,
            charge,
            discharge,
        )
        self.tank_temperature = self.temperature
        self.stored_energy, self.charge_duty, self.discharge_duty = reports
        self.heat_accumulation = charge + discharge - loss_out

        outlets = dict(charge_out=charge_out, discharge_out=discharge_out, loss_out=loss_out)
        return outlets

    def capex(self, finance):
        """Return the cost of the tank from its volume."""
        return self.capex_of(finance, self.volume)

    def _advance_states(self, inlets, outlets, dt):
        charge_in, discharge_in = inlets.charge_in, inlets.discharge_in
        relaxed = _physics.tank_relaxation(
            self.temperature,
            self._capacity(charge_in),
            dt,
            self._conductance(charge_in, self.charge_effectiveness),
            charge_in.T,
            self._conductance(discharge_in, self.discharge_effectiveness),
            discharge_in.T,
            self.heat_loss_conductance,
            inlets.air_in.T,
        )
        return {"temperature": relaxed}

    def _capacity(self, charge_in):
        """Return the tank heat capacity rho * cp * V [J/K] of ``module.fluid``."""
        properties = self.fluid.properties(charge_in.p, self.temperature)
        return _physics.tank_capacity(properties.liquid_volumetric_heat_capacity, self.volume)

    def _conductance(self, stream, effectiveness):
        """Return the circuit conductance e * m_dot * cp [W/K]; reject reverse flow."""
        ops.check(
            stream.m_dot >= 0,
            PhysicsError,
            "{path}: circuit m_dot = {m_dot} kg/s; expected >= 0 (reverse flow " "is not modelled)",
            path=self.path,
            m_dot=stream.m_dot,
        )
        return _physics.circuit_conductance(effectiveness, stream.heat_capacity_rate())

    def _circuit_heat(self, stream, effectiveness):
        """Return the heat flow [W] from a circuit into the start-of-step tank."""
        return heat_transfer.heat_rate(
            self._conductance(stream, effectiveness), stream.T - self.temperature
        )

    def _outlet_temperature(self, stream, effectiveness):
        """Return a circuit's outlet temperature [K]; a stopped circuit keeps its inlet value."""
        return ops.where(
            self._conductance(stream, effectiveness) == 0,
            stream.T,
            heat_transfer.effectiveness_outlet_temperature(
                stream.T, effectiveness, self.temperature
            ),
        )
