"""The air around the plant: the one place of the ambient conditions and of the emissions."""

from gemini import ops
from gemini.errors import PhysicsError
from gemini.modules.declarations import Boundary, Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.physics import energy, gas
from gemini.types import MassFlow, Power, Pressure, Stream, Temperature
from gemini.types.fluid import AIR
from gemini.units import Quantity


class Atmosphere(Module):
    """The air: every module that exchanges heat with it, and everything released into it.

    ``temperature``, and ``wet_bulb_temperature`` for a wet cooler, are boundaries; no other module
    keeps an ambient temperature. ``air_out`` and ``wet_air_out`` offer air at those conditions, at
    no flow, to any number of modules; a cooler returns what it took through ``air_in``. Losses
    arrive at ``heat_in`` and flue gas, flare exhaust and any released gas at ``gas_in``, and
    ``co2_emission`` and ``methane_emission`` of the whole plant are computed here and only here,
    from the composition of what arrives. ``pressure`` defaults to one standard atmosphere.
    """

    @staticmethod
    def ambient_air(temperature):
        """Return what ``air_out`` offers at ``temperature``, for a call without an atmosphere.

        ``temperature`` is a ``Quantity`` or its ``{"value", "unit"}`` dict, as ``Stream`` takes it.
        """
        return Stream(
            m_dot=Quantity(0.0, "kg/s"),
            T=temperature,
            p=Quantity(gas.NORMAL_PRESSURE, "Pa"),
            fluid=AIR,
        )

    def __init__(self):
        """Declare the ambient conditions, the air ports and what the air receives."""
        super().__init__()

        # Parameters
        self.pressure = Parameter(
            Pressure, default=gas.NORMAL_PRESSURE, gt=0, description="Ambient air pressure"
        )

        # Inlets
        self.air_in = Inlet(Stream, kind="air", many=True)
        self.heat_in = Inlet(Power, kind="heat", many=True)
        self.gas_in = Inlet(Stream, kind="gas", many=True)

        # Boundaries
        self.temperature = Boundary(Temperature, description="Ambient dry-bulb air temperature")
        self.wet_bulb_temperature = Boundary(
            Temperature | None,
            default=None,
            description="Wet-bulb temperature of the air; empty when no wet cooler is connected",
        )

        # Outputs
        self.co2_emission = Output(
            MassFlow, description="Mass flow of CO2 released into the air by the whole plant"
        )
        self.methane_emission = Output(
            MassFlow, description="Mass flow of methane released into the air by the whole plant"
        )

        # Outlets
        self.air_out = Outlet(Stream, kind="air", many=True, offered=True)
        self.wet_air_out = Outlet(Stream, kind="air", many=True, offered=True)

    def _offer(self, inlets):
        """Offer the air at the ambient conditions, at no flow."""
        wet_bulb = self.wet_bulb_temperature
        temperature = self.temperature if wet_bulb is None else wet_bulb
        temperature = ops.where(ops.isfinite(temperature), temperature, self.temperature)
        ops.check(
            temperature <= self.temperature,
            PhysicsError,
            "{path}: wet_bulb_temperature = {wet_bulb} K; expected at most temperature = {dry} K",
            path=self.path,
            wet_bulb=temperature,
            dry=self.temperature,
        )
        return {
            "air_out": Stream._si(m_dot=0.0, T=self.temperature, p=self.pressure, fluid=AIR),
            "wet_air_out": Stream._si(m_dot=0.0, T=temperature, p=self.pressure, fluid=AIR),
        }

    def forward(self, inlets):
        """Take in what the plant releases; the air gives nothing but its offer."""

        # Outputs
        self.co2_emission = self._released(inlets.gas_in, "CO2")
        self.methane_emission = self._released(inlets.gas_in, "CH4")

        outlets = dict()
        return outlets

    @staticmethod
    def _released(streams, species):
        """Return the mass flow [kg/s] of ``species`` over the released gas."""
        flows = [
            gas.species_flow(stream.m_dot, stream.fluid.gas_composition, species)
            for stream in streams
        ]
        return energy.total_power(flows)
