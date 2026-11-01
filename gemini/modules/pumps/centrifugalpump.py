"""Variable-speed centrifugal pump with a quadratic head curve and affinity-law scaling."""

from gemini import ops
from gemini.errors import PhysicsError
from gemini.modules._utils.cost import Equipment
from gemini.modules.declarations import Control, Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.physics import energy, heat_transfer, pumps
from gemini.types import (
    Efficiency,
    Fraction,
    Frequency,
    HydraulicPower,
    Power,
    PressureDifference,
    Stream,
    VolumeFlow,
)


class CentrifugalPump(Equipment, Module):
    """Centrifugal booster or circulation pump with affinity-law speed control.

    At the rated frequency the pressure rise follows the quadratic head curve
    ``H(Q) = c0 + c1 Q + c2 Q^2`` (``head_coefficients``, H in Pa and Q in m3/s). With the speed
    ratio ``s = frequency / rated_frequency`` the affinity laws (Q ~ s, H ~ s^2) give
    ``H = c0 s^2 + c1 s Q + c2 Q^2``. The hydraulic efficiency is the parabola through the
    origin with its maximum ``best_efficiency`` at the best-efficiency flow ``s * Q_bep``:
    ``eta = eta_bep * x * (2 - x)`` with ``x = Q / (s Q_bep)``, the speed-scaled quadratic
    efficiency curve of Ulanicki, Kahler and Coulbeck (2008), "Modeling the efficiency and
    power characteristics of a pump group", J. Water Resour. Plann. Manage. 134(1), 88-93.

    Hydraulic power is ``Q H``, shaft power ``Q H / eta`` and electricity the shaft power over
    ``motor_efficiency``. The pump losses ``P_shaft - P_hydraulic`` heat the liquid,
    ``dT = (P_shaft - P_hydraulic) / (m_dot cp)``, and the motor losses leave as ``loss_out``,
    so the model is first-law closed when the flow work ``Q H`` is counted. NOTE(refactor): the
    sensible-enthalpy audit of ``energy_balance`` excludes pressure energy, so its residual for
    this pump equals ``hydraulic_power``; the unit tests check that and the full closure.

    Assumptions: incompressible liquid at the suction density, constant heat capacity, an
    efficiency that does not change with speed (affinity laws, adequate for speed ratios of
    about 0.5 to 1.1), no leakage or recirculation. Valid on the curve between zero flow and
    the run-out: a flow at or beyond twice the scaled best-efficiency flow, or one that gives
    a negative head, raises ``PhysicsError``, as does reverse flow. Zero mass flow means
    the pump is stopped: no head, no power. A running pump against a closed valve (deadhead),
    whose shaft power would heat a trapped volume without bound, is outside the steady model.
    """

    equipment_kind = "circulation_pump"

    repr_fields = ("rated_frequency", "best_efficiency", "best_efficiency_flow")

    def __init__(self):
        """Declare pump design data, ports and computed performance."""
        super().__init__()

        # Parameters
        self.head_coefficients = Parameter(
            list[float], shape=(pumps.CENTRIFUGAL_HEAD_COEFFICIENT_COUNT,), calibratable=True
        )
        self.rated_frequency = Parameter(Frequency)
        self.best_efficiency = Parameter(Efficiency, calibratable=True)
        self.best_efficiency_flow = Parameter(VolumeFlow, gt=0)
        self.motor_efficiency = Parameter(Efficiency)

        # Inlets
        self.fluid_in = Inlet(Stream)
        self.power_in = Inlet(Power, kind="electricity")

        # Controls
        self.frequency = Control(Frequency)

        # Outputs
        self.head = Output(PressureDifference, soft_sensor=True)
        self.hydraulic_power = Output(HydraulicPower)
        self.shaft_power = Output(Power, soft_sensor=True)
        self.efficiency = Output(Fraction)

        # Outlets
        self.fluid_out = Outlet(Stream)
        self.loss_out = Outlet(Power, kind="heat")

    def forward(self, inlets):
        """Raise the suction pressure by the head and heat the liquid by the pump losses."""

        # Outlets
        suction = inlets.fluid_in
        performance = self._performance(suction)
        losses = performance["shaft_power"] - performance["hydraulic_power"]
        rise = heat_transfer.temperature_change(losses, suction.heat_capacity_rate())

        discharge = suction.with_(p=suction.p + performance["head"], T=suction.T + rise)
        power_in = energy.input_power(performance["shaft_power"], self.motor_efficiency)
        loss_out = power_in - performance["shaft_power"]

        # Outputs
        self.head = performance["head"]
        self.hydraulic_power = performance["hydraulic_power"]
        self.shaft_power = performance["shaft_power"]
        self.efficiency = performance["efficiency"]

        outlets = dict(fluid_out=discharge, loss_out=loss_out, power_in=power_in)
        return outlets

    def capex(self, finance):
        """Return the cost of the pump from its shaft power at the best-efficiency flow."""
        flow = self.best_efficiency_flow
        head = pumps.centrifugal_head(flow, 1.0, self.head_coefficients)
        hydraulic = pumps.hydraulic_power(flow, head)
        return self.capex_of(finance, energy.input_power(hydraulic, self.best_efficiency))

    def _performance(self, suction):
        """Return flow [m3/s], head [Pa], hydraulic and shaft power [W] and efficiency [-]."""
        flow = suction.volumetric_flow()
        ops.check(
            flow >= 0,
            PhysicsError,
            "{path}: suction volume flow = {flow} m3/s; reverse flow is unsupported",
            path=self.path,
            flow=flow,
        )
        speed = pumps.speed_ratio(self.frequency, self.rated_frequency)
        head = pumps.centrifugal_head(flow, speed, self.head_coefficients)
        load = pumps.best_efficiency_ratio(flow, speed, self.best_efficiency_flow)
        ops.check(
            ops.logical_or(
                flow == 0, ops.logical_not(ops.logical_or(head < 0, load >= pumps.RUNOUT_LOAD))
            ),
            PhysicsError,
            "{path}: flow = {flow} m3/s at frequency = {frequency} Hz gives "
            "head = {head} Pa at {load} times the best-efficiency flow; expected a "
            "nonnegative head below twice the best-efficiency flow (pump off its curve)",
            path=self.path,
            flow=flow,
            frequency=self.frequency,
            head=head,
            load=load,
        )
        efficiency = pumps.parabolic_efficiency(self.best_efficiency, load)
        hydraulic_power = pumps.hydraulic_power(flow, head)
        stopped = flow == 0
        return dict(
            flow=ops.where(stopped, 0.0, flow),
            head=ops.where(stopped, 0.0, head),
            hydraulic_power=ops.where(stopped, 0.0, hydraulic_power),
            shaft_power=ops.where(stopped, 0.0, energy.input_power(hydraulic_power, efficiency)),
            efficiency=ops.where(stopped, 0.0, efficiency),
        )
