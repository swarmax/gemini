"""Auxiliary boilers with a steady first-law heat balance: gas-fired and electric."""

from gemini import ops
from gemini.errors import PhysicsError
from gemini.modules._utils.cost import Equipment
from gemini.modules.declarations import Control, Inlet, Outlet, Output, Parameter
from gemini.modules.heating import _burner
from gemini.modules.module import Module
from gemini.physics import energy, heat_transfer
from gemini.types import Efficiency, Fuel, Power, Stream, Temperature


class _BoilerBody(Equipment, Module):
    """Water side of a boiler: heat a forward stream to its setpoint, up to a duty limit."""

    abstract = True

    def __init__(self):
        super().__init__()

        # Parameters
        self.capacity = Parameter(Power, gt=0)
        self.efficiency = Parameter(Efficiency)

        # Inlets
        self.fluid_in = Inlet(Stream, kind="hot_water")

        # Controls
        self.temperature_setpoint = Control(Temperature)

        # Outputs
        self.is_capped = Output(bool)

        # Outlets
        self.fluid_out = Outlet(Stream, kind="hot_water")

    def capex(self, finance):
        """Return the cost of the boiler from its capacity."""
        return self.capex_of(finance, self.capacity)

    def _requested_duty(self, inlet):
        """Return the duty [W] that reaches the setpoint, refusing reverse flow."""
        ops.check(
            inlet.m_dot >= 0,
            PhysicsError,
            "{path}: fluid_in.m_dot = {m_dot} kg/s; expected >= 0",
            path=self.path,
            m_dot=inlet.m_dot,
        )
        return heat_transfer.setpoint_duty(
            inlet.heat_capacity_rate(), self.temperature_setpoint - inlet.T
        )

    def _heated(self, inlet, duty):
        """Return the inlet stream heated by ``duty``."""
        rate = inlet.heat_capacity_rate()
        return inlet.with_(T=inlet.T + heat_transfer.temperature_change(duty, rate))


class Boiler(_BoilerBody):
    """Auxiliary gas boiler with a thermal capacity limit, burning co-produced gas first.

    Each step it needs ``duty / efficiency`` of fuel energy. ``fuel_in`` brings the co-produced gas:
    the boiler burns it first, up to its need, and takes the rest from the grid; the port returns
    what it burned, and a ``GasMakeup`` sends the rest to ``excess_out``. It may draw grid gas when
    ``fuel_in`` comes from a ``GasMakeup`` or a ``GasGrid``, which mark the stream with the grid
    composition; without that mark the fuel energy of the stream limits the duty.

    ``fuel`` is the fuel power [W], on no port because the gas of ``fuel_in`` may be a mixture.
    ``flue_out`` carries the CO2 of everything burned, formed and carried in the gas, to
    ``Atmosphere.gas_in``.
    """

    equipment_kind = "boiler"

    def __init__(self):
        """Declare boiler design data, ports and computed performance."""
        super().__init__()

        # Inlets
        self.fuel_in = Inlet(Stream, kind="gas", drawn=True)

        # Outputs
        self.fuel = Output(Fuel)

        # Outlets
        self.flue_out = Outlet(Stream, kind="gas")
        self.loss_out = Outlet(Power, kind="heat")

    def forward(self, inlets):
        """Heat the stream up to its setpoint and return the gas it burned."""

        # Outlets
        inlet, fuel = inlets.fluid_in, inlets.fuel_in
        requested = self._requested_duty(inlet)
        limit = self._duty_limit(fuel)
        duty = ops.minimum(requested, limit)
        outlet = self._heated(inlet, duty)
        need = energy.input_power(duty, self.efficiency)
        flue_out = _burner.flue_stream(need, fuel)

        # Outputs
        self.is_capped = requested > limit
        self.fuel = need

        outlets = dict(
            fluid_out=outlet,
            flue_out=flue_out,
            loss_out=need - duty,
            fuel_in=_burner.burned_stream(need, fuel),
        )
        return outlets

    def _duty_limit(self, fuel):
        """Return the capacity, or less when the stream alone must cover the fuel [W]."""
        if _burner.has_grid(fuel):
            return self.capacity
        useful = energy.output_power(_burner.available_fuel(fuel), self.efficiency)
        return ops.minimum(self.capacity, useful)


class ElectricBoiler(_BoilerBody):
    """Auxiliary electric boiler with a thermal capacity limit; it has no gas ports."""

    equipment_kind = "electric_boiler"

    def __init__(self):
        """Declare boiler design data, ports and computed performance."""
        super().__init__()

        # Inlets
        self.power_in = Inlet(Power, kind="electricity")

        # Outputs

        # Outlets
        self.loss_out = Outlet(Power, kind="heat")

    def forward(self, inlets):
        """Heat the stream up to its setpoint."""

        # Outlets
        inlet = inlets.fluid_in
        requested = self._requested_duty(inlet)
        duty = ops.minimum(requested, self.capacity)
        outlet = self._heated(inlet, duty)

        power_in = energy.input_power(duty, self.efficiency)

        # Outputs
        self.is_capped = requested > self.capacity

        outlets = dict(fluid_out=outlet, loss_out=power_in - duty, power_in=power_in)
        return outlets
