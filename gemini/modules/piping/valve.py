"""Control valve with an inherent flow characteristic and the IEC 60534 liquid sizing equation."""

from typing import Literal

from gemini import ops
from gemini.errors import PhysicsError
from gemini.modules._utils.flow import require_forward
from gemini.modules.declarations import Control, Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.physics import hydraulics
from gemini.types import FlowCoefficient, Fraction, PressureDifference, Ratio, Stream


class Valve(Module):
    """Control valve throttling a liquid stream; isenthalpic, so the temperature is unchanged.

    Sizing equation for non-choked turbulent liquid flow (IEC 60534-2-1:2011, Industrial-process
    control valves, Part 2-1: Flow capacity, sizing equations for fluid flow under installed
    conditions) in SI form: ``q = Kv sqrt(dp rho_0 / rho)`` with ``q`` the volume flow [m3/s],
    ``rho_0 = 1000 kg/m3`` and ``Kv`` in m3/s/Pa^0.5 (a catalogue Kv in m3/h at 1 bar converts
    with the unit ``"m3/h/bar^0.5"``), so ``dp = rho / rho_0 (q / Kv_eff)^2``. The effective
    coefficient follows the theoretical inherent characteristic of IEC 60534-2-4 with
    ``Phi_0 = 1 / rangeability``: linear ``Phi = Phi_0 + (1 - Phi_0) h`` and equal percentage
    ``Phi = Phi_0 exp(h ln(1 / Phi_0)) = R^(h - 1)``, ``Kv_eff = Phi(h) flow_coefficient`` for an
    opening ``h > 0``. A real valve leaves this curve below ``Phi_0`` and seals at ``h = 0``,
    modelled as ``Kv_eff = 0``. The default characteristic is equal percentage, the most common
    one for process control valves, and the default rangeability 50 is the typical inherent
    rangeability of globe control valves (Emerson, Control Valve Handbook, 5th ed., 2017).

    Simplifications: no choked flow or cavitation (check the outlet pressure against the vapour
    pressure; IEC 60534-2-1 ``F_L`` limits are not modelled), no installed-characteristic or
    Reynolds-number correction, constant liquid density. The throttled pressure energy
    (``dp / (rho cp)``, about 0.024 K per bar for water) is not converted into a temperature
    rise, consistent with the package's sensible-enthalpy audit. Validity: single-phase liquid
    (free gas raises ``PhysicsError``) in the marked flow direction (reverse flow raises
    ``PhysicsError``). A closed valve passes zero flow with no pressure drop; flow through
    a closed valve raises ``PhysicsError``.
    """

    def __init__(self):
        """Declare valve capacity, characteristic, opening and hydraulic outputs."""
        super().__init__()

        # Parameters
        self.flow_coefficient = Parameter(
            FlowCoefficient, gt=0, description="Valve flow coefficient Kv at full opening"
        )
        self.characteristic = Parameter(
            Literal["linear", "equal_percentage"],
            default="equal_percentage",
            description="Inherent flow characteristic of the valve",
        )
        self.rangeability = Parameter(
            Ratio,
            default=hydraulics.DEFAULT_VALVE_RANGEABILITY,
            gt=1,
            description="Ratio of the largest to the smallest controllable flow coefficient",
        )

        # Inlets
        self.fluid_in = Inlet(Stream)

        # Controls
        self.opening = Control(Fraction, description="Valve opening as a share of full travel")

        # Outputs
        self.pressure_drop = Output(
            PressureDifference, description="Pressure lost through the valve"
        )
        self.effective_flow_coefficient = Output(
            FlowCoefficient, description="Flow coefficient at the current opening"
        )

        # Outlets
        self.fluid_out = Outlet(Stream)

    def forward(self, inlets):
        """Throttle the inlet stream by the sizing-equation pressure drop."""

        # Outlets
        inlet = inlets.fluid_in
        drop = self._pressure_drop(inlet)
        ops.check(
            drop <= inlet.p,
            PhysicsError,
            "{path}: pressure drop = {drop} Pa; expected at most fluid_in.p = {inlet_p} Pa "
            "(open the valve or reduce the flow)",
            path=self.path,
            drop=drop,
            inlet_p=inlet.p,
        )
        outlet = inlet.with_(p=inlet.p - drop)

        # Outputs
        self.pressure_drop = inlets.fluid_in.p - outlet.p
        self.effective_flow_coefficient = self._effective_flow_coefficient()

        outlets = dict(fluid_out=outlet)
        return outlets

    def _effective_flow_coefficient(self):
        """Return the flow coefficient [m3/s/Pa^0.5] at the commanded opening."""
        return hydraulics.valve_flow_coefficient(
            self.flow_coefficient,
            self.opening,
            self.rangeability,
            self.characteristic == "equal_percentage",
        )

    def _pressure_drop(self, inlet):
        """Return the pressure drop [Pa] of the inlet flow at the commanded opening."""
        require_forward(self.path, "fluid_in.m_dot", inlet.m_dot)
        if inlet.fluid.gas_mass_fraction > 0:
            raise PhysicsError(
                f"{self.path}: inlet.fluid.gas_mass_fraction = "
                f"{inlet.fluid.gas_mass_fraction}; expected 0 (single-phase liquid model)"
            )
        coefficient = self._effective_flow_coefficient()
        ops.check(
            ops.logical_or(inlet.m_dot == 0, coefficient != 0),
            PhysicsError,
            "{path}: fluid_in.m_dot = {m_dot} kg/s through a closed valve "
            "(opening = 0); expected zero flow",
            path=self.path,
            m_dot=inlet.m_dot,
        )
        rho = inlet.fluid.properties(inlet.p, inlet.T).rho_l
        return hydraulics.valve_pressure_drop(inlet.m_dot, rho, coefficient)
