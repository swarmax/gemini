"""Electric vapour-compression heat pump or chiller with a Carnot- or Lorenz-fraction COP."""

from functools import partial
from typing import Literal

from gemini import ops
from gemini.errors import PhysicsError, ValidationError
from gemini.modules._utils.cost import Equipment
from gemini.modules.declarations import Control, Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.physics import heat_transfer, refrigeration
from gemini.types import (
    Efficiency,
    Fraction,
    Power,
    Ratio,
    Stream,
    Temperature,
    TemperatureDifference,
)


class HeatPump(Equipment, Module):
    """Electric vapour-compression heat pump; in cooling mode it is an electric chiller.

    The evaporator cools the ``source_in`` circuit and the condenser heats the ``sink_in``
    circuit, both water or brine. In ``heating`` mode ``temperature_setpoint`` is the sink
    outlet temperature and the useful duty is the condenser duty; in ``cooling`` mode it is the
    chilled (source) outlet temperature and the useful duty is the evaporator duty, so a
    cooling-mode heat pump is an electric chiller. The useful duty is
    ``min(requested, capacity)``; below ``minimum_part_load * capacity`` the machine is off.

    COP = carnot_fraction * T_sink_out / max(T_sink_out - T_source_out, minimum_temperature_lift)
    when heating and carnot_fraction * T_source_out / max(...) when cooling, from the outlet
    temperatures of both circuits. Because one outlet temperature depends on the COP, the
    balance Q_sink = Q_source + electricity is solved in closed form (it is linear in the
    unknown outlet temperature). The model is first-law closed.

    With ``cop_model="lorenz"`` (heating only) the COP is lorenz_fraction * T_h /
    max(T_h - T_s, minimum_temperature_lift), with T_h and T_s the log-mean temperatures of the
    sink and source glides (``refrigeration.lorenz_cop_heating``). The source outlet then enters
    the COP through a logarithm, so the balance is solved by ``brentq`` instead of in closed
    form. A cooling-mode Lorenz machine raises ``ValidationError``: the upstream GEMINI model
    it is ported from defines the Lorenz COP for heating only.

    Assumptions: constant Carnot fraction over load and temperatures (no part-load or
    compressor-map effects), no pressure loss, no heat loss from the casing, constant liquid
    heat capacity per stream. A machine with either circuit stopped does not run. Validity: a
    lift of about 10 to 80 K between outlet temperatures, the range of the water-to-water
    machines summarised by Arpagaus et al. (2018), "High temperature heat pumps: Market overview,
    state of the art, research status, refrigerants, and application potentials", Energy 152,
    985-1010, who report Carnot fractions of about 0.4 to 0.6 (default 0.5). Outlet temperatures
    are not checked against the freezing point of the fluid unless
    ``minimum_source_outlet_temperature`` is set: it caps a heating duty so the source leaves no
    colder than the minimum (upstream GEMINI ``Ts_in_minimum``) and raises a cooling setpoint
    below it to the minimum.

    Every branch of the operating point is evaluated and selected with ``where``; a stopped
    circuit has a zero capacity rate, whose temperature change ``heat_transfer.temperature_change``
    takes as zero. The two ``ops.brentq`` solves (the Lorenz source outlet and the source-limited
    duty) are functions of ``refrigeration`` called through their ``args``; a
    solve that fails gives NaN and raises ``PhysicsError`` where its row is selected.
    """

    def __init__(self):
        """Declare heat pump design data, both circuits and computed performance."""
        super().__init__()

        # Parameters
        self.mode = Parameter(Literal["heating", "cooling"])
        self.capacity = Parameter(Power, gt=0)
        self.cop_model = Parameter(Literal["carnot", "lorenz"], default="carnot")
        self.carnot_fraction = Parameter(Efficiency, default=refrigeration.DEFAULT_CARNOT_FRACTION)
        self.lorenz_fraction = Parameter(Efficiency, default=refrigeration.DEFAULT_LORENZ_FRACTION)
        self.minimum_temperature_lift = Parameter(
            TemperatureDifference, default=refrigeration.DEFAULT_MINIMUM_LIFT, gt=0
        )
        self.minimum_part_load = Parameter(Fraction, default=0)
        self.minimum_source_outlet_temperature = Parameter(Temperature | None, default=None)

        # Inlets
        self.source_in = Inlet(Stream)
        self.sink_in = Inlet(Stream, kind="hot_water")
        self.power_in = Inlet(Power, kind="electricity")

        # Controls
        self.temperature_setpoint = Control(Temperature)

        # Outputs
        self.cop = Output(Ratio | None)
        self.temperature_lift = Output(TemperatureDifference)
        self.is_capped = Output(bool)
        self.is_running = Output(bool)

        # Outlets
        self.source_out = Outlet(Stream)
        self.sink_out = Outlet(Stream, kind="hot_water")

    def forward(self, inlets):
        """Cool the source and heat the sink circuit by the solved duties."""

        # Outlets
        values = self._performance(inlets.source_in, inlets.sink_in)
        source_out = inlets.source_in.with_(T=values["source_out_T"])
        sink_out = inlets.sink_in.with_(T=values["sink_out_T"])

        # Outputs
        self.cop = values["cop"]
        self.temperature_lift = values["temperature_lift"]
        self.is_capped = values["is_capped"]
        self.is_running = values["is_running"]

        outlets = dict(source_out=source_out, sink_out=sink_out, power_in=values["electricity"])
        return outlets

    @property
    def equipment_kind(self):
        """The kind of equipment: a ``heat_pump``, or a ``compression_chiller`` in cooling mode."""
        return "compression_chiller" if self.mode == "cooling" else "heat_pump"

    def capex(self, finance):
        """Return the cost of the machine from its capacity."""
        return self.capex_of(finance, self.capacity)

    def _performance(self, source_in, sink_in):
        """Return every output; the outlet temperatures [K] also define the outlets."""
        source_rate = _rate(self.path, "source_in", source_in)
        sink_rate = _rate(self.path, "sink_in", sink_in)
        heating = self.mode == "heating"
        if self.cop_model == "lorenz" and not heating:
            raise ValidationError(
                f"{self.path}: cop_model = 'lorenz' with mode = 'cooling'; expected "
                "mode = 'heating' (the Lorenz COP is defined for heating only)",
                code="invalid_design",
            )
        operate = self._heating if heating else self._cooling
        duty, is_capped, source_T, sink_T = operate(source_in, sink_in, source_rate, sink_rate)
        running = duty != 0
        cop = self._cop(source_in, sink_in, source_T, sink_T)
        evaporator, condenser = duty, duty
        if heating:
            evaporator = ops.where(running, refrigeration.heating_evaporator_duty(duty, cop), duty)
        if not heating:
            condenser = ops.where(running, refrigeration.cooling_condenser_duty(duty, cop), duty)
        return {
            "cop": ops.where(running, cop, None),
            "useful_duty": duty,
            "evaporator_duty": evaporator,
            "condenser_duty": condenser,
            "electricity": condenser - evaporator,
            "temperature_lift": sink_T - source_T,
            "is_capped": is_capped,
            "is_running": duty > 0,
            "source_out_T": source_T,
            "sink_out_T": sink_T,
        }

    def _heating(self, source_in, sink_in, source_rate, sink_rate):
        """Return the heating duty [W], the capped flag and the source and sink outlets [K].

        The sink is heated towards the setpoint. When the source outlet would fall below
        ``minimum_source_outlet_temperature``, the duty is reduced until the source leaves at
        that minimum (``_duty_at_source_limit``), the sink outlet drops with it and the machine
        reports ``is_capped``.
        """
        requested = heat_transfer.setpoint_duty(sink_rate, self.temperature_setpoint - sink_in.T)
        duty = self._duty(requested, source_rate, sink_rate)
        sink_T = sink_in.T + heat_transfer.temperature_change(duty, sink_rate)
        source_T = self._source_outlet_T(source_in, sink_in, source_rate, sink_T, duty)
        capped = requested > self.capacity
        limit = self.minimum_source_outlet_temperature
        if limit is not None:
            below = ops.logical_not(source_T >= limit)
            limited = self._duty_at_source_limit(
                source_in,
                sink_in,
                source_rate,
                sink_rate,
                duty,
                ops.logical_and(below, duty != 0),
            )
            limited_duty = self._duty(ops.where(below, limited, duty), source_rate, sink_rate)
            duty = ops.where(below, limited_duty, duty)
            capped = ops.where(below, True, capped)
            source_T = ops.where(below, limit, source_T)
            sink_T = ops.where(
                below, sink_in.T + heat_transfer.temperature_change(duty, sink_rate), sink_T
            )
        stopped = duty == 0
        return (
            ops.where(stopped, 0.0, duty),
            ops.where(stopped, False, capped),
            ops.where(stopped, source_in.T, source_T),
            ops.where(stopped, sink_in.T, sink_T),
        )

    def _cooling(self, source_in, sink_in, source_rate, sink_rate):
        """Return the cooling duty [W], the capped flag and the source and sink outlets [K].

        The source is cooled towards the setpoint, raised to
        ``minimum_source_outlet_temperature`` when that is warmer; a raised setpoint reports
        ``is_capped``.
        """
        limit = self.minimum_source_outlet_temperature
        setpoint = self.temperature_setpoint
        is_limited = False
        if limit is not None:
            is_limited = setpoint < limit
            setpoint = ops.where(is_limited, limit, setpoint)
        requested = heat_transfer.setpoint_duty(source_rate, source_in.T - setpoint)
        duty = self._duty(requested, source_rate, sink_rate)
        source_T = source_in.T - heat_transfer.temperature_change(duty, source_rate)
        sink_T = self._sink_outlet_T(sink_in.T, sink_rate, source_T, duty)
        stopped = duty == 0
        capped = ops.logical_or(requested > self.capacity, is_limited)
        return (
            ops.where(stopped, 0.0, duty),
            ops.where(stopped, False, capped),
            ops.where(stopped, source_in.T, source_T),
            ops.where(stopped, sink_in.T, sink_T),
        )

    def _duty(self, requested, source_rate, sink_rate):
        """Return the delivered useful duty [W]: zero with a stopped circuit, else part load."""
        stopped = ops.logical_or(source_rate == 0, sink_rate == 0)
        duty = refrigeration.part_load_duty(
            requested, self.capacity, ops.where(stopped, 0.0, self.minimum_part_load)
        )
        return ops.where(stopped, 0.0, duty)

    def _duty_at_source_limit(self, source_in, sink_in, source_rate, sink_rate, duty, selected):
        """Return the heating duty [W] whose evaporator cools the source exactly to its minimum.

        The evaporator may take at most C_source (T_in - T_min). Its demand Q (1 - 1 / COP),
        with the sink outlet T_sink_in + Q / C_sink and the source outlet T_min in the COP,
        rises from zero at Q = 0 to more than the available heat at the requested duty, whose
        unconstrained source outlet is colder than T_min; ``brentq`` finds the duty between.
        A source inlet at or below the minimum leaves no duty. The solve is checked only where
        ``selected``: the other rows of the batch may have no root.
        """
        limit = self.minimum_source_outlet_temperature
        available = heat_transfer.heat_rate(source_rate, source_in.T - limit)
        root = ops.brentq(
            partial(refrigeration.source_limit_shortfall, self._cop_function()),
            0.0,
            duty,
            args=(
                sink_in.T,
                sink_rate,
                source_in.T,
                limit,
                available,
                self._efficiency(),
                self.minimum_temperature_lift,
            ),
        )
        ops.check(
            ops.logical_or(ops.logical_not(selected), ops.logical_or(available <= 0, root == root)),
            PhysicsError,
            "{path}: no heating duty between 0 W and {duty} W cools the source to "
            "{limit} K; expected a source below the minimum at the requested duty",
            path=self.path,
            duty=duty,
            limit=limit,
        )
        return ops.where(available <= 0, 0.0, root)

    def _efficiency(self):
        """Return the Carnot or Lorenz fraction of the COP model [-]."""
        if self.cop_model == "lorenz":
            return self.lorenz_fraction
        return self.carnot_fraction

    def _cop_function(self):
        """Return the COP function of the mode and COP model, which all take the same arguments."""
        if self.cop_model == "lorenz":
            return refrigeration.lorenz_fraction_cop_heating
        if self.mode == "heating":
            return refrigeration.carnot_fraction_cop_heating
        return refrigeration.carnot_fraction_cop_cooling

    def _cop(self, source_in, sink_in, source_T, sink_T):
        """Return the COP [-] of the mode and COP model at the given outlet temperatures [K]."""
        return self._cop_function()(
            self._efficiency(),
            self.minimum_temperature_lift,
            sink_in.T,
            sink_T,
            source_in.T,
            source_T,
        )

    def _source_outlet_T(self, source_in, sink_in, rate, sink_T, duty):
        """Return the source outlet [K] that balances a heating duty [W] at sink outlet sink_T.

        The Carnot balance is linear in the source outlet
        (``refrigeration.carnot_heating_source_outlet``); the Lorenz COP is solved numerically by
        ``_lorenz_source_outlet_T``.
        """
        if self.cop_model == "lorenz":
            return self._lorenz_source_outlet_T(source_in, sink_in, rate, sink_T, duty)
        inlet_T = source_in.T
        fluid_out_T = refrigeration.carnot_heating_source_outlet(
            inlet_T,
            heat_transfer.temperature_change(duty, rate),
            sink_T,
            self.carnot_fraction,
            self.minimum_temperature_lift,
        )
        ops.check(
            ops.where(duty == 0, True, self._cop(source_in, sink_in, fluid_out_T, sink_T) > 1),
            PhysicsError,
            "{path}: source_in.T = {inlet_T} K; expected above {minimum} K for a heating COP "
            "above 1 at sink outlet {sink_T} K",
            path=self.path,
            inlet_T=inlet_T,
            minimum=refrigeration.heating_cop_minimum_source(sink_T, self.carnot_fraction),
            sink_T=sink_T,
        )
        return fluid_out_T

    def _lorenz_source_outlet_T(self, source_in, sink_in, rate, sink_T, duty):
        """Return the source outlet [K] that balances a heating duty [W] with the Lorenz COP.

        The evaporator balance C (T_in - x) = Q (1 - 1 / COP(x)) has its root between
        x = T_in - Q / C, where the left side alone covers the duty, and x = T_in, where it is
        zero; ``brentq`` finds it to within 2e-12 K. A COP of 1 or less already at x = T_in
        means no source outlet can supply the evaporator duty.
        """
        arguments = (
            rate,
            source_in.T,
            sink_in.T,
            sink_T,
            duty,
            self.lorenz_fraction,
            self.minimum_temperature_lift,
        )
        lower = source_in.T - heat_transfer.temperature_change(duty, rate)
        at_inlet = refrigeration.lorenz_source_surplus(source_in.T, *arguments)
        ops.check(
            ops.where(duty == 0, True, ops.logical_and(lower > 0, at_inlet < 0)),
            PhysicsError,
            "{path}: source_in.T = {inlet_T} K, source_in.m_dot * cp = {rate} W/K; expected a "
            "source that supplies the duty {duty} W with a heating COP above 1 at sink outlet "
            "{sink_T} K",
            path=self.path,
            inlet_T=source_in.T,
            rate=rate,
            duty=duty,
            sink_T=sink_T,
        )
        root = ops.brentq(
            refrigeration.lorenz_source_surplus,
            ops.where(lower > 0, lower, source_in.T),
            source_in.T,
            args=arguments,
        )
        self._check_lorenz_root(root, lower, source_in.T, duty, sink_T)
        return root

    def _check_lorenz_root(self, root, lower, inlet_T, duty, sink_T):
        """Reject a failed evaporator solve on the rows that have a duty."""
        ops.check(
            ops.logical_or(duty == 0, root == root),
            PhysicsError,
            "{path}: no source outlet between {lower} K and {inlet_T} K balances the "
            "evaporator duty {duty} W at sink outlet {sink_T} K",
            path=self.path,
            lower=lower,
            inlet_T=inlet_T,
            duty=duty,
            sink_T=sink_T,
        )

    def _sink_outlet_T(self, inlet_T, rate, source_T, duty):
        """Return the sink outlet [K] that rejects a cooling duty [W] at source outlet source_T.

        The balance is linear in the sink outlet
        (``refrigeration.carnot_cooling_sink_outlet``) and needs a sink capacity rate above
        ``refrigeration.cooling_minimum_sink_rate`` unless the lift floor applies.
        """
        fluid_out_T, within_floor, denominator = refrigeration.carnot_cooling_sink_outlet(
            inlet_T,
            heat_transfer.temperature_change(duty, rate),
            source_T,
            self.carnot_fraction,
            self.minimum_temperature_lift,
        )
        ops.check(
            ops.logical_or(ops.logical_or(duty == 0, within_floor), denominator > 0),
            PhysicsError,
            "{path}: sink_in.m_dot * cp = {rate} W/K; expected above {minimum} W/K to reject "
            "the cooling duty {duty} W",
            path=self.path,
            rate=rate,
            minimum=refrigeration.cooling_minimum_sink_rate(duty, self.carnot_fraction, source_T),
            duty=duty,
        )
        return fluid_out_T


def _rate(path, port, stream):
    """Return a stream's heat capacity rate m_dot * cp [W/K]; reject negative flow."""
    ops.check(
        stream.m_dot >= 0,
        PhysicsError,
        "{path}: {port}.m_dot = {m_dot} kg/s; expected >= 0",
        path=path,
        port=port,
        m_dot=stream.m_dot,
    )
    return stream.heat_capacity_rate()
