"""Space or process heat demand on a hydronic circuit with a steady first-law balance."""

from gemini import ops
from gemini.errors import PhysicsError, ValidationError
from gemini.modules.declarations import Boundary, Control, Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.physics import heat_transfer
from gemini.types import WATER, MassFlow, Power, Pressure, Stream, Temperature


class HeatingGrid(Module):
    """Heat consumer that cools the supply stream by the delivered heat demand.

    The circuit's mass flow is imposed by the supply stream (the consumer has no flow control),
    so the return temperature follows from the delivered heat:

    Q_available = m_dot cp max(0, T_supply - T_return,min)
    Q = min(heat_demand, Q_available)
    T_return = T_supply - Q / (m_dot cp)

    The return temperature is floored at ``minimum_return_temperature``, the lowest
    temperature the consumer's emitters or process heat exchanger can cool the water to (for
    example the space temperature plus an emitter approach, or a legionella or process limit).
    Demand beyond ``Q_available`` is ``unmet_demand``. A supply colder than the minimum return
    temperature delivers nothing and returns unchanged; the consumer never heats the water.

    On a closed loop ``return_temperature``, ``return_pressure`` and the control ``flow`` set the
    return water: ``return_out`` is offered before the other modules run, the heat delivered is the
    fall of the water from ``supply_in`` to ``return_out``, what is short of ``heat_demand`` is
    ``unmet_demand``, never an error, and what the water gives above it is ``surplus``. Bind
    ``heat_demand`` to a ``gm.data.from_csv`` column. Without them the return follows from
    the demand, as in a substation.

    Simplifications: steady state without circuit inventory, constant fluid properties (the
    inlet ``cp``), no pressure drop (pipes and valves carry the hydraulics) and no emitter
    characteristic: whether the emitters can actually transfer ``heat_demand`` at the given
    temperatures is the caller's assumption, bounded only by the return floor. There is no
    design return temperature parameter, because with an imposed flow it would not change the
    result. Mass is conserved and the model is first-law closed: the sensible enthalpy drop of
    the stream equals ``heat_supplied``. Valid for liquid water, brine or glycol circuits at any
    temperature above freezing, with nonnegative flow.

    Reference: the steady hydronic heat balance Q = m_dot cp (T_supply - T_return), ASHRAE
    Handbook - HVAC Systems and Equipment (2020), chapter 13, "Hydronic heating and cooling".
    """

    def __init__(self):
        """Declare the consumer's return limit, demand boundary and delivered heat."""
        super().__init__()
        self.fluid = WATER

        # Parameters
        self.minimum_return_temperature = Parameter(Temperature | None, default=None)
        self.return_temperature = Parameter(
            Temperature | None,
            default=None,
            structural=True,
            case="demand.heating.return_temperature",
        )
        self.minimum_supply_temperature = Parameter(
            Temperature | None, default=None, case="demand.heating.supply_temperature"
        )
        self.return_pressure = Parameter(Pressure | None, default=None)

        # Inlets
        self.supply_in = Inlet(Stream, kind="hot_water")

        # Controls
        self.flow = Control(MassFlow | None, default=None, ge=0)

        # Boundaries
        self.heat_demand = Boundary(Power, ge=0)

        # Outputs
        self.unmet_demand = Output(Power)
        self.surplus = Output(Power)
        self.is_unmet = Output(bool)

        # Outlets
        self.return_out = Outlet(Stream, kind="hot_water", offered=True)

    def forward(self, inlets):
        """Return the supply stream cooled by the delivered heat."""

        # Outlets
        supply_in = inlets.supply_in
        if self.return_temperature is None:
            delivered = self._delivered_heat(supply_in)
            return_out = supply_in.with_(T=self._cooled_temperature(supply_in, delivered))
        else:
            return_out = self._offer(inlets)["return_out"]
            delivered = heat_transfer.heat_rate(
                supply_in.heat_capacity_rate(), supply_in.T - return_out.T
            )

        # Outputs
        self.unmet_demand = ops.maximum(self.heat_demand - delivered, 0.0)
        self.surplus = ops.maximum(delivered - self.heat_demand, 0.0)
        self.is_unmet = self.unmet_demand > 0

        outlets = dict(return_out=return_out)
        return outlets

    def _loop_start(self, port, entering):
        """Start a building loop at the lowest return temperature."""
        return self.minimum_return_temperature

    def _offers(self):
        """Offer only on a closed loop; otherwise the outlet follows from the inlet."""
        return self.return_temperature is not None

    def _offer(self, inlets):
        """Offer the return water of a closed loop, at the fixed temperature and the given flow."""
        if self.return_temperature is None or self.return_pressure is None or self.flow is None:
            raise ValidationError(
                f"{self.path}: return_temperature, return_pressure and flow are needed to offer "
                "return_out; expected all three on a closed loop",
                code="invalid_design",
            )
        offered = Stream(
            m_dot=self.flow, T=self.return_temperature, p=self.return_pressure, fluid=self.fluid
        )
        return {"return_out": offered}

    def _cooled_temperature(self, supply_in, delivered):
        """Return the return temperature [K] after the users took ``delivered`` [W]."""
        capacity_rate = supply_in.heat_capacity_rate()
        cooled = ops.maximum(
            self.minimum_return_temperature,
            supply_in.T - heat_transfer.temperature_change(delivered, capacity_rate),
        )
        return ops.where(delivered == 0, supply_in.T, cooled)

    def _delivered_heat(self, supply_in):
        """Return the delivered heat [W]: the demand, capped by the return-temperature floor."""
        ops.check(
            supply_in.m_dot >= 0,
            PhysicsError,
            "{path}: supply_in.m_dot = {m_dot} kg/s; expected >= 0",
            path=self.path,
            m_dot=supply_in.m_dot,
        )
        if self.minimum_return_temperature is None:
            raise ValidationError(
                f"{self.path}: minimum_return_temperature = None; expected a value without a "
                "return_temperature",
                code="missing_value",
            )
        available = heat_transfer.setpoint_duty(
            supply_in.heat_capacity_rate(), supply_in.T - self.minimum_return_temperature
        )
        return ops.minimum(self.heat_demand, available)
