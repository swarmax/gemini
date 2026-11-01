"""Ideal-gas compressor for separated non-condensable gas."""

from gemini import ops
from gemini.errors import PhysicsError
from gemini.modules.declarations import Control, Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.modules.pumps import _physics
from gemini.physics import energy
from gemini.types import Count, Efficiency, Power, Pressure, Ratio, SpecificHeat, Stream


class GasCompressor(Module):
    """Electric compressor raising the gas from a degasser or separator to a pressure setpoint.

    The gas is an ideal gas with the constant ``gas_specific_heat`` ``cp`` and
    ``heat_capacity_ratio`` ``k``; both are required because the non-condensable gas of
    geothermal brines ranges from nearly pure CO2 to methane-rich mixtures. The suction
    ``Stream`` carries the gas mass flow in ``m_dot`` (as ``Degasser.gas_out`` does); its ``fluid``
    is passed through unchanged and its liquid property model is not used. The overall pressure
    ratio ``r = pressure_setpoint / p_suction`` is split equally over ``stage_count`` adiabatic
    stages with intercoolers that return the gas to the suction temperature
    (``_physics``, GPSA Engineering Data Book, 14th ed., Section 13):

    ``T_2 = T_1 + T_1 (r**((k - 1) / (k N)) - 1) / eta_s``,
    ``P_shaft = m_dot N cp (T_2 - T_1)``, ``electricity = P_shaft / motor_efficiency``.

    The gas leaves the last stage at ``T_2`` (no aftercooler). ``loss_out`` is the
    intercooler duty ``m_dot (N - 1) cp (T_2 - T_1)`` plus the motor losses, so the model is
    first-law closed in gas enthalpy: ``electricity = m_dot cp (T_2 - T_1) + heat_loss``.
    NOTE(refactor): ``energy_balance`` values every stream with its fluid's liquid ``cp_l``, not
    the gas ``cp``, so its sensible audit is not valid for this module; the unit tests check the
    closure in gas enthalpy instead.

    Valid for gases near ideal behaviour (compressibility factor close to one) and stage
    pressure ratios up to about 4, the usual limit set by the discharge temperature. A
    setpoint below the suction pressure (expansion) and reverse flow raise
    ``PhysicsError``; at zero gas flow the compressor draws no power and the discharge
    temperature is the one the gas would have.
    """

    repr_fields = ("stage_count", "isentropic_efficiency", "heat_capacity_ratio")

    def __init__(self):
        """Declare compressor design data, ports and computed performance."""
        super().__init__()

        # Parameters
        self.isentropic_efficiency = Parameter(
            Efficiency, calibratable=True, description="Isentropic efficiency of the compression"
        )
        self.heat_capacity_ratio = Parameter(
            Ratio, gt=1, description="Ratio of specific heats of the gas (cp over cv)"
        )
        self.gas_specific_heat = Parameter(
            SpecificHeat, description="Specific heat capacity at constant pressure of the gas"
        )
        self.stage_count = Parameter(
            Count,
            default=1,
            description="Number of compression stages sharing the pressure ratio equally",
        )
        self.motor_efficiency = Parameter(
            Efficiency, description="Efficiency of the motor: shaft power over electric power drawn"
        )

        # Inlets
        self.fluid_in = Inlet(Stream, kind="gas")
        self.power_in = Inlet(Power, kind="electricity")

        # Controls
        self.pressure_setpoint = Control(
            Pressure, description="Discharge pressure the compressor raises the gas to"
        )

        # Outputs
        self.pressure_ratio = Output(
            Ratio, description="Outlet over suction pressure of the compressor"
        )
        self.shaft_power = Output(
            Power, soft_sensor=True, description="Mechanical power on the compressor shaft"
        )

        # Outlets
        self.fluid_out = Outlet(Stream, kind="gas")
        self.loss_out = Outlet(Power, kind="heat")

    def forward(self, inlets):
        """Compress the gas to the pressure setpoint and heat it by the last stage."""

        # Outlets
        suction = inlets.fluid_in
        pressure_ratio = self._pressure_ratio(suction)
        stage_ratio = _physics.stage_pressure_ratio(pressure_ratio, self.stage_count)
        fluid_out_T = _physics.stage_outlet_temperature(
            suction.T, stage_ratio, self.heat_capacity_ratio, self.isentropic_efficiency
        )

        discharge = suction.with_(p=self.pressure_setpoint, T=fluid_out_T)
        shaft_power = self._shaft_power(suction)
        power_in = energy.input_power(shaft_power, self.motor_efficiency)
        loss_out = _physics.heat_rejected(power_in, shaft_power, self.stage_count)

        # Outputs
        self.pressure_ratio = pressure_ratio
        self.shaft_power = shaft_power

        outlets = dict(fluid_out=discharge, loss_out=loss_out, power_in=power_in)
        return outlets

    def _shaft_power(self, suction):
        """Return the shaft power [W] of the compression at the operating point."""
        work = _physics.specific_compression_work(
            suction.T,
            self._pressure_ratio(suction),
            self.heat_capacity_ratio,
            self.gas_specific_heat,
            self.isentropic_efficiency,
            self.stage_count,
        )
        return _physics.shaft_power(suction.m_dot, work)

    def _pressure_ratio(self, suction):
        """Return the overall pressure ratio [-]; reject reverse flow and expansion."""
        ops.check(
            ops.logical_not(suction.m_dot < 0),
            PhysicsError,
            "{path}: fluid_in.m_dot = {m_dot} kg/s; reverse flow is unsupported",
            path=self.path,
            m_dot=suction.m_dot,
        )
        ops.check(
            ops.logical_not(ops.logical_or(suction.p <= 0, self.pressure_setpoint < suction.p)),
            PhysicsError,
            "{path}: pressure_setpoint = {setpoint} Pa, fluid_in.p = {p} Pa; expected a "
            "positive suction pressure at or below the setpoint",
            path=self.path,
            setpoint=self.pressure_setpoint,
            p=suction.p,
        )
        return _physics.overall_pressure_ratio(self.pressure_setpoint, suction.p)
