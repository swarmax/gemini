"""Two-stream effectiveness-NTU heat exchanger."""

from typing import Literal

import numpy as np

from gemini import ops
from gemini.errors import PhysicsError
from gemini.modules._utils.cost import Equipment
from gemini.modules.declarations import Inlet, Outlet, Output, Parameter
from gemini.modules.module import Module
from gemini.physics import diagnostics, heat_transfer, hydraulics
from gemini.types import (
    Duty,
    Fraction,
    Health,
    MassFlow,
    PressureDifference,
    Ratio,
    Stream,
    Temperature,
    TemperatureDifference,
    ThermalConductance,
)
from gemini.types.results import NOT_ASSESSED


class HeatExchanger(Equipment, Module):
    """Two-stream heat exchanger with thermal and fouling diagnostics."""

    equipment_kind = "heat_exchanger"

    repr_fields = (
        "thermal_conductance",
        "arrangement",
        "hot_nominal_pressure_drop",
        "cold_nominal_pressure_drop",
    )

    def __init__(self):
        """Declare exchanger design data, ports and computed performance."""
        super().__init__()

        # Parameters
        self.thermal_conductance = Parameter(ThermalConductance, calibratable=True)
        self.arrangement = Parameter(Literal["counterflow", "parallel"], default="counterflow")
        self.hot_nominal_pressure_drop = Parameter(PressureDifference, ge=0)
        self.cold_nominal_pressure_drop = Parameter(PressureDifference, ge=0)
        self.hot_nominal_mass_flow = Parameter(MassFlow, gt=0)
        self.cold_nominal_mass_flow = Parameter(MassFlow, gt=0)
        self.fouling_threshold = Parameter(
            Fraction, default=diagnostics.DEFAULT_FOULING_THRESHOLD, gt=0, le=1
        )

        # Inlets
        self.hot_in = Inlet(Stream)
        self.cold_in = Inlet(Stream)

        # Outputs
        self.duty = Output(Duty, soft_sensor=True)
        self.effectiveness = Output(Fraction, soft_sensor=True)
        self.transfer_units = Output(Ratio)
        self.log_mean_temperature_difference = Output(TemperatureDifference)
        self.hot_out_T = Output(Temperature)
        self.cold_out_T = Output(Temperature)
        self.hot_pressure_drop = Output(PressureDifference)
        self.cold_pressure_drop = Output(PressureDifference)
        self.approach_temperature = Output(TemperatureDifference)

        # Outlets
        self.hot_out = Outlet(Stream)
        self.cold_out = Outlet(Stream)

    def forward(self, inlets):
        """Solve the heat balance and retain both streams' mass flows."""

        # Outlets
        hot_in = inlets.hot_in
        cold_in = inlets.cold_in
        values = self._performance(hot_in, cold_in)

        hot_out = hot_in.with_(T=values["hot_out_T"], p=hot_in.p - values["hot_pressure_drop"])
        cold_out = cold_in.with_(T=values["cold_out_T"], p=cold_in.p - values["cold_pressure_drop"])

        # Outputs
        for name, value in values.items():
            setattr(self, name, value)

        outlets = dict(hot_out=hot_out, cold_out=cold_out)
        return outlets

    def _loop_limits(self, inlets):
        """Keep a loop on one side of what comes in on the other: the exchanger must not reverse."""
        cold, hot = inlets.get("cold_in"), inlets.get("hot_in")
        return (None if cold is None else cold.T), (None if hot is None else hot.T)

    def capex(self, finance):
        """Return the cost of the exchanger from its thermal conductance."""
        return self.capex_of(finance, self.thermal_conductance)

    def _performance(self, hot_in, cold_in):
        self._check_inlets(hot_in, cold_in)
        effectiveness, ntu, duty, hot_T, cold_T = heat_transfer.exchanger_balance(
            hot_in.T,
            cold_in.T,
            hot_in.heat_capacity_rate(),
            cold_in.heat_capacity_rate(),
            self.thermal_conductance,
            self.arrangement == "counterflow",
        )
        hot_pressure_drop = hydraulics.quadratic_pressure_drop(
            self.hot_nominal_pressure_drop, hot_in.m_dot, self.hot_nominal_mass_flow
        )
        cold_pressure_drop = hydraulics.quadratic_pressure_drop(
            self.cold_nominal_pressure_drop, cold_in.m_dot, self.cold_nominal_mass_flow
        )
        dt1, dt2 = heat_transfer.terminal_differences(
            hot_in.T, hot_T, cold_in.T, cold_T, self.arrangement == "counterflow"
        )
        return {
            "duty": duty,
            "effectiveness": effectiveness,
            "transfer_units": ntu,
            "log_mean_temperature_difference": heat_transfer.lmtd(
                ops.maximum(0.0, dt1), ops.maximum(0.0, dt2)
            ),
            "hot_out_T": hot_T,
            "cold_out_T": cold_T,
            "hot_pressure_drop": hot_pressure_drop,
            "cold_pressure_drop": cold_pressure_drop,
            "approach_temperature": ops.minimum(dt1, dt2),
        }

    def _check_inlets(self, hot_in, cold_in):
        """Reject negative flow and a hot inlet below the cold inlet of a running exchanger."""
        ops.check(
            ops.logical_and(hot_in.m_dot >= 0, cold_in.m_dot >= 0),
            PhysicsError,
            "{path}: negative mass flow hot_in.m_dot = {hot_m_dot} kg/s, "
            "cold_in.m_dot = {cold_m_dot} kg/s; expected >= 0",
            path=self.path,
            hot_m_dot=hot_in.m_dot,
            cold_m_dot=cold_in.m_dot,
        )
        stopped = ops.logical_or(hot_in.m_dot == 0, cold_in.m_dot == 0)
        ops.check(
            ops.logical_or(hot_in.T >= cold_in.T, stopped),
            PhysicsError,
            "{path}: hot inlet is below cold inlet: hot_in.T = {hot_T} K, "
            "cold_in.T = {cold_T} K",
            path=self.path,
            hot_T=hot_in.T,
            cold_T=cold_in.T,
        )

    def health(self, result, measured):
        """Alarm when apparent conductance falls below the configured design fraction.

        With measured outlet temperatures, the inlet temperatures, mass flows and heat capacities
        come from the call's inlet streams. Returns ``None`` (not assessed) when a measurement is
        missing, the design UA is zero, or no row of the measurements can determine an apparent
        UA (see ``gm.analysis.estimate_conductance``). On arrays the rows that cannot are not
        ``assessed``, as a module without health reports them: score one, no alarm,
        ``NOT_ASSESSED``, NaN metrics.
        """
        if {"hot_out_T", "cold_out_T"} <= measured.keys():
            measured = measured | _inlet_measurements(result.inlets)
        keys = ("hot_in_T", "hot_out_T", "cold_in_T", "cold_out_T", "m_dot_hot", "m_dot_cold")
        if not set(keys) <= measured.keys() or not self.thermal_conductance:
            return None
        apparent, code, _, _, _ = heat_transfer.apparent_conductance(
            self.arrangement,
            *(measured[key] for key in keys),
            measured.get("cp_hot", heat_transfer.DEFAULT_CP),
            measured.get("cp_cold", heat_transfer.DEFAULT_CP),
        )
        assessed = code == heat_transfer.DETERMINED
        if not np.any(assessed):
            return None
        ratio = diagnostics.performance_ratio(apparent, self.thermal_conductance)
        alarm = diagnostics.below_limit(ratio, self.fouling_threshold)
        return Health(
            assessed=assessed,
            score=ops.where(assessed, diagnostics.bounded_score(ratio), 1.0),
            alarm=ops.where(assessed, alarm, False),
            message=ops.where(
                assessed,
                ops.where(alarm, "Apparent UA below fouling limit", "Apparent UA within limit"),
                NOT_ASSESSED,
            ),
            metrics={
                "apparent_ua": ops.where(assessed, apparent, float("nan")),
                "ua_ratio": ops.where(assessed, ratio, float("nan")),
            },
        )


def _inlet_measurements(inlets):
    """Return inlet temperatures [K], mass flows [kg/s] and heat capacities [J/kg/K]."""
    hot, cold = inlets.hot_in, inlets.cold_in
    return dict(
        hot_in_T=hot.T,
        cold_in_T=cold.T,
        m_dot_hot=hot.m_dot,
        m_dot_cold=cold.m_dot,
        cp_hot=hot.fluid.properties(hot.p, hot.T).cp_l,
        cp_cold=cold.fluid.properties(cold.p, cold.T).cp_l,
    )
