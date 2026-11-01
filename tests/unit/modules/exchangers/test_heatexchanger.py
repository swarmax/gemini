"""Heat exchanger energy balances and validation against the example plant dataset."""

import numpy as np
import pandas as pd
import pytest

import gemini as gm
from gemini import units
from gemini.modules.exchangers import HeatExchanger
from gemini.physics import heat_transfer
from gemini.types.flows import Stream
from gemini.types.fluid import WATER
from gemini.types.results import NOT_ASSESSED
from scripts.legacy import tables as mapping
from tests.fixtures import OLD_PROJECT
from tests.fixtures.designs import with_values
from tests.fixtures.equivalence import assert_health_matches, assert_module_matches
from tests.fixtures.errors import raises

BRINE_DENSITY = 1050
"""Brine density [kg/m3] that, with the retained cp = 4217.4 J/kg/K, reproduces the CSV duty.

NOTE(refactor): the CSV implies rho*cp = 4.410 MJ/m3/K, unlike default water's 4.2174; density
1050 kg/m3 with the retained cp predicts duty within 0.5 %.
"""


WATER_CP = {
    "cp_hot": heat_transfer.DEFAULT_CP,
    "cp_cold": heat_transfer.DEFAULT_CP,
    "arrangement": "counterflow",
}


def measured_row(row):
    """Return the SI terminal measurements of one old CSV row."""
    return dict(
        hot_in_T=units.c_to_k(row.T_p_in),
        hot_out_T=units.c_to_k(row.T_p_out),
        cold_in_T=units.c_to_k(row.T_s_in),
        cold_out_T=units.c_to_k(row.T_s_out),
        m_dot_hot=units.m3h_to_m3s(row.Qp) * BRINE_DENSITY,
        m_dot_cold=units.m3h_to_m3s(row.Qs) * BRINE_DENSITY,
    )


def exchanger_for(row, measured, ua):
    """Return the example heat exchanger sized for one row and the inlet streams."""
    base = mapping.heatexchanger_params_from_gemini(
        mapping.from_property(OLD_PROJECT / "heat_exchanger_3410.param")
    )
    params = base | dict(
        thermal_conductance=ua,
        hot_nominal_pressure_drop=units.bar_to_pa(row.HEX_PDrop),
        cold_nominal_pressure_drop=0,
        hot_nominal_mass_flow=measured["m_dot_hot"],
        cold_nominal_mass_flow=measured["m_dot_cold"],
    )
    streams = {
        "hot_in": Stream(
            m_dot=measured["m_dot_hot"], T=measured["hot_in_T"], p=units.bar_to_pa(row.HEX_Pin)
        ),
        "cold_in": Stream(
            m_dot=measured["m_dot_cold"], T=measured["cold_in_T"], p=1e6, fluid=WATER
        ),
    }
    return with_values(HeatExchanger()).set_params("", params), streams


def test_measured_heat_exchanger_performance():
    """Fit UA from measured terminal temperatures, then reproduce duty, temperatures and loss."""
    rows = pd.read_csv(OLD_PROJECT / "doublet_2024_old.csv", sep=";", nrows=5)
    for _, row in rows.iterrows():
        measured = measured_row(row)
        ua = gm.analysis.estimate_conductance(**measured, **WATER_CP)["value"]
        exchanger, streams = exchanger_for(row, measured, ua)
        result = exchanger(**streams)
        out = result.outputs
        assert out.hot_out_T == pytest.approx(measured["hot_out_T"], abs=0.5)
        assert out.cold_out_T == pytest.approx(measured["cold_out_T"], abs=0.5)
        assert out.duty == pytest.approx(row.Thermal_PowerGen, rel=0.02)
        assert 10000 < out.hot_pressure_drop < 20000
        assert not exchanger.health(result, measured).alarm
        fouled, _ = exchanger_for(row, measured, ua * 0.8)
        reduced = fouled(**streams).outputs
        degraded = measured | dict(hot_out_T=reduced.hot_out_T, cold_out_T=reduced.cold_out_T)
        assert exchanger.health(result, degraded).alarm


@pytest.mark.parametrize("arrangement", ["parallel", "counterflow"])
def test_first_law_equal_capacity_and_limits(arrangement):
    """Both arrangements conserve energy, retain mass and respect zero-flow/zero-UA limits."""
    p = dict(
        thermal_conductance=100000,
        arrangement=arrangement,
        hot_nominal_pressure_drop=1000,
        cold_nominal_pressure_drop=2000,
        hot_nominal_mass_flow=10,
        cold_nominal_mass_flow=10,
    )
    c = with_values(HeatExchanger()).set_params("", p)
    hot, cold = Stream(m_dot=10, T=350, p=1e6), Stream(m_dot=10, T=300, p=1e6)
    result = c(hot_in=hot, cold_in=cold)
    out, streams = result.outputs, result.outlets
    assert (hot.T - out.hot_out_T) * 10 * 4217.4 == pytest.approx(out.duty)
    assert (out.cold_out_T - cold.T) * 10 * 4217.4 == pytest.approx(out.duty)
    assert streams["hot_out"].m_dot == hot.m_dot and streams["cold_out"].m_dot == cold.m_dot
    assert streams["hot_out"].p == hot.p - 1000
    out = c(hot_in=hot.with_(m_dot=0), cold_in=cold).outputs
    assert out.duty == 0
    c.set_params("", {"thermal_conductance": 0})
    out = c(hot_in=hot, cold_in=cold).outputs
    assert out.duty == 0 and out.hot_out_T == hot.T
    out = c(hot_in=hot, cold_in=cold.with_(T=350)).outputs
    assert out.duty == 0 and out.log_mean_temperature_difference == 0


def test_invalid_measurements():
    """A temperature cross or a gross heat-balance mismatch cannot identify a valid UA."""
    with raises(gm.errors.PhysicsError, "too_little_data"):
        gm.analysis.estimate_conductance(350, 340, 300, 340, 10, 10, **WATER_CP)


def test_health_is_not_assessed_when_measurements_cannot_determine_ua():
    """E-modules-011/012: zero flow or zero design UA mean not assessed, not an error."""
    exchanger = with_values(HeatExchanger()).set_params(
        "",
        {
            "thermal_conductance": 100000,
            "hot_nominal_pressure_drop": 1000,
            "cold_nominal_pressure_drop": 1000,
            "hot_nominal_mass_flow": 10,
            "cold_nominal_mass_flow": 10,
        },
    )
    stopped = exchanger(
        hot_in=Stream(m_dot=0, T=350, p=1e6), cold_in=Stream(m_dot=10, T=300, p=1e6)
    )
    measured = dict(hot_out_T=340, cold_out_T=310)
    assert exchanger.health(stopped, measured) is None
    running = exchanger(
        hot_in=Stream(m_dot=10, T=350, p=1e6), cold_in=Stream(m_dot=10, T=300, p=1e6)
    )
    assert exchanger.health(running, measured) is not None
    exchanger.set_params("", {"thermal_conductance": 0})
    assert exchanger.health(running, measured) is None
    with raises(gm.errors.ValidationError, "unknown_name", match="arrangement"):
        gm.analysis.estimate_conductance(
            350, 340, 300, 310, 10, 10, **{**WATER_CP, "arrangement": "cross"}
        )


@pytest.mark.parametrize("arrangement", ["parallel", "counterflow"])
def test_traced_call_matches_one_call_per_row(arrangement):
    """Unequal, equal, stopped and pinched rows trace and equal one call per row."""
    exchanger = with_values(HeatExchanger()).set_params(
        "",
        {
            "thermal_conductance": 100000,
            "arrangement": arrangement,
            "hot_nominal_pressure_drop": 1000,
            "cold_nominal_pressure_drop": 2000,
            "hot_nominal_mass_flow": 10,
            "cold_nominal_mass_flow": 10,
        },
    )
    rows = [
        dict(hot_in=Stream(m_dot=hot, T=hot_T, p=1e6), cold_in=Stream(m_dot=cold, T=300, p=1e6))
        for hot, cold, hot_T in [
            (10, 10, 350),
            (5, 12, 360),
            (12, 5, 340),
            (0, 10, 350),
            (10, 0, 350),
            (0, 0, 350),
            (10, 10, 300),
        ]
    ]
    assert_module_matches(exchanger, rows)


def _health_exchanger(arrangement):
    return with_values(HeatExchanger()).set_params(
        "",
        {
            "thermal_conductance": 100000,
            "arrangement": arrangement,
            "hot_nominal_pressure_drop": 1000,
            "cold_nominal_pressure_drop": 2000,
            "hot_nominal_mass_flow": 10,
            "cold_nominal_mass_flow": 10,
            "fouling_threshold": 0.15,
        },
    )


@pytest.mark.parametrize("arrangement", ["parallel", "counterflow"])
def test_health_on_arrays_matches_one_call_per_row(arrangement):
    """Fouled, clean and better-than-design rows give the scores, alarms and messages per row."""
    exchanger = _health_exchanger(arrangement)
    streams = dict(hot_in=Stream(m_dot=10, T=350, p=1e6), cold_in=Stream(m_dot=10, T=300, p=1e6))
    result = exchanger(**streams)
    clean = result.outputs
    rows = [
        dict(hot_out_T=clean.hot_out_T, cold_out_T=clean.cold_out_T),
        dict(hot_out_T=clean.hot_out_T + 8, cold_out_T=clean.cold_out_T - 8),
        dict(hot_out_T=clean.hot_out_T - 0.05, cold_out_T=clean.cold_out_T + 0.05),
        dict(hot_out_T=clean.hot_out_T + 3, cold_out_T=clean.cold_out_T - 3),
    ]
    assert_health_matches(exchanger, [result] * len(rows), rows)
    alarms = [exchanger.health(result, row).alarm for row in rows]
    assert alarms.count(True) >= 1 and alarms.count(False) >= 1


def test_health_on_arrays_marks_undetermined_rows_not_assessed():
    """A row with a gross duty mismatch is not assessed; a chunk without any gives None."""
    exchanger = _health_exchanger("counterflow")
    result = exchanger(
        hot_in=Stream(m_dot=10, T=350, p=1e6), cold_in=Stream(m_dot=10, T=300, p=1e6)
    )
    outputs = result.outputs
    measured = dict(
        hot_out_T=np.array([outputs.hot_out_T, outputs.hot_out_T]),
        cold_out_T=np.array([outputs.cold_out_T, 340.0]),
    )
    health = exchanger.health(result, measured)
    assert health.assessed.tolist() == [True, False]
    assert health.score[1] == 1.0 and not health.alarm[1]
    assert health.message[1] == NOT_ASSESSED and np.isnan(health.metrics["apparent_ua"][1])
    assert health.score[0] == exchanger.health(result, {k: v[0] for k, v in measured.items()}).score
    assert exchanger.health(result, {k: v[1:] for k, v in measured.items()}) is None
