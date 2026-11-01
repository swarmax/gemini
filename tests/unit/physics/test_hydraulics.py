"""Pipe friction, Beggs–Brill two-phase flow, path marching and radial inflow."""

import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from gemini import ops
from gemini.errors import PhysicsError, ValidationError
from gemini.physics import diagnostics, geometry, hydraulics
from gemini.types.flows import Stream
from gemini.types.fluid import BRINE, Fluid
from gemini.units import Quantity
from tests.fixtures.equivalence import assert_function_matches, assert_same_error
from tests.fixtures.errors import raises
from tests.unit.test_golden import assert_values

GOLDEN = json.loads((Path(__file__).parents[2] / "fixtures/golden_values.json").read_text())
FLUID_PROPERTIES = (1.976, 1000.0)
GAS = Fluid(gas_mass_fraction=0.01)


def _path(*diameters):
    """Return a vertical path of 100 m sections with the given internal diameters."""
    return geometry.PipePath(
        sections=[
            geometry.PipeSection(
                length=100, inclination=math.pi / 2, inner_diameter=d, roughness=2e-5
            )
            for d in diameters
        ]
    )


@pytest.mark.parametrize("role", ["production", "injection"])
def test_path_golden(role):
    """Path marching preserves every original section pressure and temperature."""
    case = GOLDEN["well_" + role]
    p = case["parameters"]
    u = case["inputs"]
    path = geometry.PipePath(
        sections=[
            geometry.PipeSection(length=length, inclination=a, inner_diameter=d, roughness=r)
            for length, a, d, r in zip(p["length"], p["angle"], p["diameter"], p["roughness"])
        ]
    )
    stream = SimpleNamespace(m_dot=u["flowrate"] * 1000, p=u["pressure"], T=u["temperature"])
    result = hydraulics.pipe_path_profile(
        path, stream, BRINE, u["direction"], 10, u["temperature_ambient"]
    )
    assert_values(
        dict(
            pressure_output=result.p_out,
            temperature_output=result.T_out,
            pressuredrop_fric_output=result.friction_pressure_drop,
            pressuredrop_grav_output=result.gravity_pressure_drop,
            section_pressure_output=result.section_pressure,
            section_temperature_output=result.section_temperature,
        ),
        case["expected"],
    )


def test_darcy_and_beggs_brill_goldens():
    """Both pressure-drop correlations reproduce the original phase-0 cases."""
    assert hydraulics.darcy_weisbach_dp(*GOLDEN["darcy"]["inputs"]) == pytest.approx(
        GOLDEN["darcy"]["expected"], rel=1e-9
    )
    assert hydraulics.beggs_brill_dp(*GOLDEN["beggs"]["inputs"]) == pytest.approx(
        GOLDEN["beggs"]["expected"], rel=1e-9
    )


def test_darcy_friction_follows_the_flow_sign():
    """Reverse flow reverses friction; zero velocity leaves only gravity."""
    forward = hydraulics.darcy_weisbach_dp(2, 1000, 0.5, 1e-3, 0.1778, 2e-5, 100)
    reverse = hydraulics.darcy_weisbach_dp(-2, 1000, 0.5, 1e-3, 0.1778, 2e-5, 100)
    assert reverse == (-forward[0], forward[1])
    assert hydraulics.darcy_weisbach_dp(0, 1000, 0.5, 1e-3, 0.1778, 2e-5, 100) == (
        0.0,
        forward[1],
    )


@pytest.mark.parametrize(
    "us_l,inclination,diameter,expected",
    [
        (0.5, -0.1, 0.05, ("0x1.91c0499b9cdcfp+12", "-0x1.7e9094ec4ae5ap+16")),
        (0.5, 0.1, 0.05, ("0x1.91c0499b9cdcfp+12", "0x1.7e9094ec4ae5ap+16")),
        (0.5, -0.1, 0.1778, ("0x1.e1f2464fc2d34p+10", "-0x1.4e56f79e456d8p+16")),
        (0.5, 0.1, 0.1778, ("0x1.e1f1bef7430d7p+10", "0x1.4e603be43ea52p+16")),
        (0.0001, -0.1, 0.05, ("0x1.5e800bad3ce89p-8", "-0x1.a6b80ba0b55cap+15")),
        (0.0001, 0.1, 0.05, ("0x1.3748a32308d58p-8", "0x1.7e9094ec4ae5ap+16")),
        (0.05, -0.1, 0.05, ("0x1.df0f84de7a0adp+6", "-0x1.7e9094ec4ae5ap+16")),
        (0.05, 0.0, 0.05, ("0x1.df0f84de7a0adp+6", "0x0.0p+0")),
    ],
)
def test_beggs_brill_pinned_bits_in_every_regime(us_l, inclination, diameter, expected):
    """Distributed, intermittent, segregated and transition flow keep their original bits."""
    friction, gravity = hydraulics.beggs_brill_dp(
        0.0001, us_l, *FLUID_PROPERTIES, inclination, 21.29e-6, 1e-3, 0.0728, diameter, 2e-5, 100
    )
    assert (friction.hex(), gravity.hex()) == expected


def test_flow_regime_map_and_exact_boundaries():
    """The exact no-slip holdup 0.4 falls into the upper regime of the map."""
    assert hydraulics._flow_regime(0.005, 1.0)[0] == hydraulics._SEGREGATED
    assert hydraulics._flow_regime(0.2, 1e4)[0] == hydraulics._DISTRIBUTED
    assert hydraulics._flow_regime(0.01, 100.0)[0] == hydraulics._DISTRIBUTED
    assert hydraulics._flow_regime(0.4, 1.0)[0] == hydraulics._INTERMITTENT
    assert hydraulics._flow_regime(0.4, 1e4)[0] == hydraulics._DISTRIBUTED
    with pytest.raises(PhysicsError, match="flow-regime map"):
        hydraulics._flow_regime(float("nan"), 1.0)


def test_beggs_brill_exact_boundary_no_longer_divides_by_zero():
    """No-slip holdup exactly 0.4 formerly matched no regime and raised ZeroDivisionError."""
    friction, gravity = hydraulics.beggs_brill_dp(
        0.6, 0.4, *FLUID_PROPERTIES, math.pi / 2, 21.29e-6, 1e-3, 0.0728, 0.2, 2e-5, 100
    )
    assert friction > 0 and gravity > 0


def test_beggs_brill_rejects_zero_holdup_and_missing_liquid():
    """Steep downhill flow can clamp the holdup to zero; pure gas has no liquid number."""
    with pytest.raises(PhysicsError, match="holdup = 0"):
        hydraulics.beggs_brill_dp(
            0.5, 0.05, *FLUID_PROPERTIES, -math.pi / 4, 21.29e-6, 1e-3, 0.0728, 0.1778, 2e-5, 100
        )
    with pytest.raises(PhysicsError, match="us_l = 0"):
        hydraulics.beggs_brill_dp(
            0.5, 0, *FLUID_PROPERTIES, 0.7, 21.29e-6, 1e-3, 0.0728, 0.1778, 2e-5, 100
        )


def test_two_phase_reverse_flow_reverses_friction():
    """Negative two-phase flow formerly took the logarithm of a negative Reynolds number."""
    path = _path(0.18, 0.18)
    forward = Stream(
        m_dot=Quantity(40, "kg/s"), T=Quantity(350, "K"), p=Quantity(20e5, "Pa"), fluid=GAS
    )
    reverse = Stream(
        m_dot=Quantity(-40, "kg/s"), T=Quantity(350, "K"), p=Quantity(20e5, "Pa"), fluid=GAS
    )
    ahead = hydraulics.pipe_path_profile(path, forward, GAS, "down", 0, 300)
    back = hydraulics.pipe_path_profile(path, reverse, GAS, "down", 0, 300)
    assert back.friction_pressure_drop == pytest.approx(-ahead.friction_pressure_drop)
    assert back.gravity_pressure_drop == pytest.approx(ahead.gravity_pressure_drop)


def test_zero_flow_unknown_correlation_and_direction():
    """Preserve DPDT zero-flow behavior and reject unknown correlations and directions."""
    path = _path(0.18)
    stream = Stream(m_dot=Quantity(0, "kg/s"), p=Quantity(1e6, "Pa"), T=Quantity(350, "K"))
    result = hydraulics.pipe_path_profile(path, stream, BRINE, "up", 10, 290)
    assert result.p_out == stream.p and result.T_out == stream.T
    assert result.friction_pressure_drop == result.gravity_pressure_drop == 0
    assert hydraulics.pipe_path_profile(path, stream, BRINE, " Up ", 10, 290) == result
    with raises(ValidationError, "unknown_name", match="'unknown'"):
        hydraulics.pipe_path_profile(path, stream, BRINE, "up", 10, 290, correlation="unknown")
    with pytest.raises(ValueError, match="direction = 'sideways'"):
        hydraulics.pipe_path_profile(path, stream, BRINE, "sideways", 10, 290)


def test_corrosion_profile_pairs_sections_in_traversal_order():
    """A capitalised direction formerly paired downward results with reversed sections."""
    path = _path(0.1, 0.3)
    stream = Stream(m_dot=Quantity(40, "kg/s"), T=Quantity(350, "K"), p=Quantity(50e5, "Pa"))
    chemistry = {"co2_fraction": 0.05}
    lower = hydraulics.corrosion_profile(path, stream, BRINE, "down", 0, 350, chemistry, "DLD")
    upper = hydraulics.corrosion_profile(path, stream, BRINE, "Down", 0, 350, chemistry, "DLD")
    assert upper == lower
    assert lower[0] != lower[1]


def test_erosion_check_compares_each_section():
    """Narrow sections run faster and raise the API alarm first."""
    result = hydraulics.erosion_check(
        _path(0.02, 0.3),
        Stream(m_dot=Quantity(40, "kg/s"), T=Quantity(350, "K"), p=Quantity(50e5, "Pa")),
        BRINE,
    )
    assert result["velocity"][0] > result["limit"] > result["velocity"][1]
    assert result["alarm"] is True
    assert [s["exceeds_api_limit"] for s in result["sections"]] == [True, False]


def test_radial_pressure_drops_and_hydrostatics():
    """Radial Darcy and skin drops scale with flow; nonpositive geometry is rejected."""
    flow_pressure_drop, skin_pressure_drop = hydraulics.radial_pressure_drops(
        0.04, 6.5e-4, 1e-11, 45, 1000, 0.0765, 2
    )
    assert flow_pressure_drop == pytest.approx(
        0.04 * 6.5e-4 * math.log(1000 / 0.0765) / (2 * math.pi * 1e-11 * 45)
    )
    assert skin_pressure_drop == pytest.approx(0.04 * 6.5e-4 * 2 / (2 * math.pi * 1e-11 * 45))
    with pytest.raises(PhysicsError, match="thickness = 0"):
        hydraulics.radial_pressure_drops(0.04, 6.5e-4, 1e-11, 0, 1000, 0.0765, 2)
    assert hydraulics.hydrostatic_dp(1000, 10) == pytest.approx(98100)


BEGGS_ROWS = [
    (0.0001, us_l, *FLUID_PROPERTIES, inclination, 21.29e-6, 1e-3, 0.0728, diameter, 2e-5, 100)
    for us_l, inclination, diameter in (
        (0.5, -0.1, 0.05),
        (0.5, 0.1, 0.05),
        (0.5, -0.1, 0.1778),
        (0.5, 0.1, 0.1778),
        (0.0001, -0.1, 0.05),
        (0.0001, 0.1, 0.05),
        (0.05, -0.1, 0.05),
        (0.05, 0.0, 0.05),
        (0.4, math.pi / 2, 0.2),
    )
] + [(0.6, 0.4, *FLUID_PROPERTIES, math.pi / 2, 21.29e-6, 1e-3, 0.0728, 0.2, 2e-5, 100)]


def test_darcy_weisbach_matches_on_arrays():
    """Forward, reverse and zero velocity give the same drops on arrays and floats."""
    rows = [(velocity, 1000, 0.5, 1e-3, 0.1778, 2e-5, 100) for velocity in (2, -2, 0, 1e-4, 0.3)]
    assert_function_matches(hydraulics.darcy_weisbach_dp, rows)


def test_beggs_brill_matches_on_arrays():
    """Every regime, both inclination signs and the transition blend match on arrays."""
    assert_function_matches(hydraulics.beggs_brill_dp, BEGGS_ROWS)


def test_beggs_brill_errors_match_on_arrays():
    """Zero liquid, zero holdup and a pair outside the regime map raise the same messages."""
    zero_liquid = (0.5, 0, *FLUID_PROPERTIES, 0.7, 21.29e-6, 1e-3, 0.0728, 0.1778, 2e-5, 100)
    zero_holdup = (
        0.5,
        0.05,
        *FLUID_PROPERTIES,
        -math.pi / 4,
        21.29e-6,
        1e-3,
        0.0728,
        0.1778,
        2e-5,
        100,
    )
    outside = (0.5, math.nan, *FLUID_PROPERTIES, 0.7, 21.29e-6, 1e-3, 0.0728, 0.1778, 2e-5, 100)
    for row in (zero_liquid, zero_holdup, outside):
        assert_same_error(hydraulics.beggs_brill_dp, [BEGGS_ROWS[0], row], PhysicsError)


def test_flow_regime_and_friction_multiplier_match_on_arrays():
    """The regime map, its boundaries and both multiplier branches match on arrays."""
    assert_function_matches(
        hydraulics._flow_regime,
        [(0.005, 1.0), (0.2, 1e4), (0.01, 100.0), (0.4, 1.0), (0.4, 1e4), (0.05, 5.0), (0.3, 1.5)],
    )
    assert_function_matches(
        hydraulics._friction_multiplier, [(0.2, 0.5), (0.5, 0.45), (0.3, 0.9), (0.9, 0.95)]
    )


def test_radial_drops_and_hydrostatics_match_on_arrays():
    """Radial drops, their check and the hydrostatic head match on arrays."""
    rows = [
        (0.04, 6.5e-4, 1e-11, 45, 1000, 0.0765, 2),
        (-0.04, 6.5e-4, 1e-11, 45, 500, 0.1, 0),
    ]
    assert_function_matches(hydraulics.radial_pressure_drops, rows)
    assert_same_error(
        hydraulics.radial_pressure_drops,
        rows + [(0.04, 6.5e-4, 1e-11, 0.0, 1000.0, 0.0765, 2)],
        PhysicsError,
    )
    assert_function_matches(hydraulics.hydrostatic_dp, [(1000, 10), (1020, -5)])


def _profile(path, fluid, direction):
    """Return a physics function of the stream fields, so a traced stream is seen as traced."""

    @ops.physics
    def profile(m_dot, p, T):
        stream = Stream._si(m_dot=m_dot, p=p, T=T, fluid=fluid)
        result = hydraulics.pipe_path_profile(path, stream, fluid, direction, 10, 290)
        return dict(
            p_out=result.p_out,
            T_out=result.T_out,
            friction_pressure_drop=result.friction_pressure_drop,
            gravity_pressure_drop=result.gravity_pressure_drop,
            **{f"p{i}": value for i, value in enumerate(result.section_pressure)},
            **{f"T{i}": value for i, value in enumerate(result.section_temperature)},
        )

    return profile


@pytest.mark.parametrize("direction", ["up", "down"])
@pytest.mark.parametrize("fluid", [BRINE, GAS], ids=["liquid", "two_phase"])
def test_pipe_path_profile_matches_on_arrays(fluid, direction):
    """Forward, reverse and zero flow match on arrays, for liquid and two-phase fluids."""
    rows = [(40, 20e5, 350), (-40, 20e5, 350), (0, 20e5, 350), (5, 1e5, 330), (400, 1e5, 330)]
    profile = _profile(_path(0.18, 0.1), fluid, direction)
    profile.__name__ = "pipe_path_profile"
    assert_function_matches(profile, rows)


def test_two_phase_zero_flow_in_a_steep_downhill_section_returns_zero_drops():
    """Zero flow with free gas leaves pressure and temperature, even where Beggs-Brill fails."""
    path = geometry.PipePath(
        sections=[
            geometry.PipeSection(
                length=100, inclination=-math.pi / 4, inner_diameter=0.1778, roughness=2e-5
            )
        ]
    )
    stream = Stream(
        m_dot=Quantity(0, "kg/s"), p=Quantity(1e6, "Pa"), T=Quantity(350, "K"), fluid=GAS
    )
    result = hydraulics.pipe_path_profile(path, stream, GAS, "down", 10, 290)
    assert (result.p_out, result.T_out) == (1e6, 350)
    assert result.friction_pressure_drop == result.gravity_pressure_drop == 0


def test_two_phase_zero_flow_rows_match_on_arrays_in_a_steep_downhill_section():
    """Stopped rows cross the failing Beggs-Brill checks of a steep section without raising."""
    path = geometry.PipePath(
        sections=[
            geometry.PipeSection(
                length=100, inclination=-math.pi / 4, inner_diameter=0.1778, roughness=2e-5
            )
        ]
    )
    profile = _profile(path, GAS, "down")
    profile.__name__ = "pipe_path_profile"
    assert_function_matches(profile, [(0, 1e6, 350), (0, 5e5, 330)])


def test_erosion_check_matches_on_arrays():
    """Section velocities, ratios and the alarm over a narrow and a wide section match."""

    @ops.physics
    def check(m_dot, p, T):
        result = hydraulics.erosion_check(
            _path(0.02, 0.3),
            Stream._si(m_dot=m_dot, p=p, T=T, fluid=BRINE),
            BRINE,
        )
        return dict(
            limit=result["limit"],
            alarm=result["alarm"],
            **{f"velocity{index}": value for index, value in enumerate(result["velocity"])},
            **{
                f"ratio{index}": section["velocity_ratio"]
                for index, section in enumerate(result["sections"])
            },
        )

    check.__name__ = "erosion_check"
    assert_function_matches(check, [(40, 50e5, 350), (0.5, 50e5, 350), (-40, 20e5, 330)])


def test_corrosion_profile_matches_on_arrays():
    """The corrosion rate of every section of the marched profile matches on arrays."""

    @ops.physics
    def profile(m_dot, p, T):
        stream = Stream._si(m_dot=m_dot, p=p, T=T, fluid=BRINE)
        rates = hydraulics.corrosion_profile(
            _path(0.1, 0.3), stream, BRINE, "down", 0, 350, {"co2_fraction": 0.05}, "DLD"
        )
        return {f"rate{index}": rate for index, rate in enumerate(rates)}

    profile.__name__ = "corrosion_profile"
    assert_function_matches(profile, [(40, 50e5, 350), (10, 30e5, 340), (-40, 50e5, 350)])


def test_quadratic_pressure_drop_scales_with_the_flow_squared():
    """Twice the reference flow gives four times the reference drop, in either direction."""
    assert hydraulics.quadratic_pressure_drop(1600, 2.0, 1.0) == 6400
    assert hydraulics.quadratic_pressure_drop(1600, -1.0, 2.0) == 400
    assert_function_matches(
        hydraulics.quadratic_pressure_drop,
        [(1600.0, 44.2, 44.2), (1600.0, 0.0, 44.2), (1e5, -30.0, 45.0)],
    )


def test_valve_pressure_drop_follows_the_iec_sizing_equation():
    """Water at the rated Kv loses one reference pressure unit; zero flow loses nothing."""
    assert hydraulics.valve_pressure_drop(1000.0, 1000.0, 1.0) == 1.0
    assert hydraulics.valve_pressure_drop(0.0, 1000.0, 0.0) == 0.0
    assert_function_matches(
        hydraulics.valve_pressure_drop,
        [(10.0, 1000.0, 1e-4), (0.0, 1000.0, 0.0), (5.0, 1068.0, 5.4e-5)],
    )


def test_reynolds_number_by_hand():
    """Re = |u| rho D / mu: 2 m/s of water in a 0.1 m pipe at 1 mPa s is 2e5, sign ignored."""
    assert hydraulics.reynolds_number(2.0, 1000.0, 0.1, 1e-3) == pytest.approx(2e5)
    assert hydraulics.reynolds_number(2.0, 1000.0, 0.1, 1e-3) == pytest.approx(2e5)


def test_reynolds_number_matches_on_arrays():
    """Forward, reverse and zero velocity give the same Reynolds number on arrays and floats."""
    rows = [(velocity, 1000.0, 0.1778, 1e-3) for velocity in (2.0, -2.0, 0.0, 1e-4)]
    assert_function_matches(hydraulics.reynolds_number, rows)


def test_hydrostatic_dp_by_hand_and_inclination():
    """Pressure is rho g h s: 100 m of water is 981 kPa; a 30 degree run halves it."""
    assert hydraulics.hydrostatic_dp(1000.0, 100.0) == pytest.approx(981000.0)
    assert hydraulics.hydrostatic_dp(1000.0, 100.0, 0.5) == pytest.approx(490500.0)


def test_hydrostatic_dp_matches_on_arrays():
    """The inclination factor runs on arrays as on floats, with and without its default."""
    assert_function_matches(hydraulics.hydrostatic_dp, [(1000.0, 100.0), (850.0, -20.0)])
    assert_function_matches(hydraulics.hydrostatic_dp, [(1000.0, 100.0, 0.5), (850.0, -20.0, -1.0)])


def test_pipe_friction_drop_by_hand_in_each_regime():
    """Laminar water in a 0.1 m pipe follows 32 mu L u / D^2; turbulent follows Darcy-Weisbach."""
    laminar = hydraulics.pipe_friction_drop(0.01, 1000.0, 1e-3, 0.1, 4.5e-5, 100.0)
    assert laminar == pytest.approx(32 * 1e-3 * 100 * 0.01 / 0.1**2)
    turbulent = hydraulics.pipe_friction_drop(2.0, 1000.0, 1e-3, 0.1, 4.5e-5, 100.0)
    assert turbulent == hydraulics.darcy_weisbach_dp(2.0, 1000.0, 0.0, 1e-3, 0.1, 4.5e-5, 100.0)[0]
    assert hydraulics.pipe_friction_drop(0.0, 1000.0, 1e-3, 0.1, 4.5e-5, 100.0) == 0.0


def test_pipe_friction_drop_bridges_the_transition_and_matches_on_arrays():
    """The drop is continuous across Re 2300 to 4000 and every regime agrees on arrays."""
    low = hydraulics.pipe_friction_drop(0.0229999, 1000.0, 1e-3, 0.1, 4.5e-5, 100.0)
    high = hydraulics.pipe_friction_drop(0.0230001, 1000.0, 1e-3, 0.1, 4.5e-5, 100.0)
    assert low == pytest.approx(high, rel=1e-4)
    velocities = (0.0, 0.01, 0.03, 0.04, 0.05, 2.0)
    rows = [(v, 1000.0, 1e-3, 0.1, 4.5e-5, 100.0) for v in velocities]
    assert_function_matches(hydraulics.pipe_friction_drop, rows)


def test_pipe_conductance_by_hand_and_on_arrays():
    """UA = U pi D L: 10 W/m2/K on 0.1 m by 100 m is 100 pi W/K."""
    assert hydraulics.pipe_conductance(10.0, 0.1, 100.0) == pytest.approx(100 * math.pi)
    assert_function_matches(hydraulics.pipe_conductance, [(10.0, 0.1, 100.0), (0.0, 0.2, 5.0)])


def test_valve_flow_coefficient_by_hand_and_on_arrays():
    """Equal percentage gives R^(h-1), linear gives 1/R at the floor, closed gives zero."""
    assert hydraulics.valve_flow_coefficient(2.0, 1.0, 50.0, True) == pytest.approx(2.0)
    assert hydraulics.valve_flow_coefficient(1.0, 0.5, 50.0, True) == pytest.approx(50**-0.5)
    assert hydraulics.valve_flow_coefficient(1.0, 0.5, 50.0, False) == pytest.approx(0.51)
    assert hydraulics.valve_flow_coefficient(1.0, 0.0, 50.0, True) == 0.0
    rows = [(1.0, h, 50.0) for h in (0.0, 0.3, 1.0)]
    assert_function_matches(hydraulics.valve_flow_coefficient, rows, equal_percentage=True)
    assert_function_matches(hydraulics.valve_flow_coefficient, rows, equal_percentage=False)


def test_affine_correction_and_inflow_relations_by_hand():
    """The affine correction, the linear inflow laws and the indices that invert them."""
    assert hydraulics.affine_correction(1e7, 1.1, -5e4) == pytest.approx(1.095e7)
    assert hydraulics.productivity_pressure(2e7, 0.01, 1e-7) == pytest.approx(1.99e7)
    assert hydraulics.injectivity_pressure(2e7, 0.01, 1e-7) == pytest.approx(2.01e7)
    assert hydraulics.productivity_index(0.01, 2e7, 1.99e7) == pytest.approx(1e-7)
    assert hydraulics.injectivity_index(0.01, 2e7, 2.01e7) == pytest.approx(1e-7)
    assert diagnostics.performance_ratio(0.8, 2.0) == 0.4


def test_affine_correction_and_inflow_relations_match_on_arrays():
    """Each relation runs on arrays as on floats."""
    rows = [(2e7, 0.01, 1e-7), (1.5e7, 0.02, 3e-7)]
    for function in (
        hydraulics.affine_correction,
        hydraulics.productivity_pressure,
        hydraulics.injectivity_pressure,
        hydraulics.productivity_index,
        hydraulics.injectivity_index,
    ):
        assert_function_matches(function, rows)
    assert_function_matches(diagnostics.performance_ratio, [(0.8, 2.0), (3.0, 1.5)])


def test_radial_index_inverts_the_radial_drops():
    """The index times the two drops at a flow gives the flow back."""
    args = (4e-4, 2e-13, 100.0, 1000.0, 0.122, 1.0)
    index = hydraulics.radial_index(*args)
    assert sum(hydraulics.radial_pressure_drops(0.08, *args)) * index == pytest.approx(0.08)


def test_hydrostatic_pressure_is_absolute():
    """A column open to the atmosphere."""
    assert hydraulics.hydrostatic_pressure(1000.0, 0.0) == 101325


def test_pump_setting_depth_keeps_the_intake_pressure():
    """The column above the depth falls to the intake pressure; never above the surface."""
    depth = hydraulics.pump_setting_depth(2500.0, 2.5e7, 2.4e6, 1e6, 1030.0)
    column = hydraulics.hydrostatic_dp(1030.0, 2500.0 - depth)
    assert 2.5e7 - 2.4e6 - column == pytest.approx(1e6)
    assert hydraulics.pump_setting_depth(100.0, 2.5e7, 0.0, 1e5, 1000.0) == 0


def test_design_pump_head_closes_the_pressure_balance():
    """Wellhead, column and friction against the flowing bottomhole pressure."""
    head = hydraulics.design_pump_head(1e6, 2.5e7, 2.4e6, 1030.0, 4e-4, 2500.0, 0.244, 4.5e-5, 0.08)
    gravity = hydraulics.hydrostatic_dp(1030.0, 2500.0)
    friction = head - (1e6 + gravity - 2.5e7 + 2.4e6)
    assert 0 < friction < 1e6
    assert hydraulics.design_pump_head(0.0, 1e9, 0.0, 1000.0, 1e-3, 10.0, 0.2, 1e-5, 0.01) == 0


def test_the_gas_superficial_velocity_is_the_gas_mass_flow_over_its_density_and_area(monkeypatch):
    """10 kg/s with x = 1e-3 of gas at 1.976 kg/m3 in a 0.2 m pipe is 0.1611 m/s, by hand.

    m_g = 1e-3 * 10 = 0.01 kg/s, A = pi 0.2**2 / 4 = 0.03142 m2, us_g = 0.01 / 1.976 / 0.03142.
    """
    seen = {}

    def spy(us_g, us_l, *rest):
        seen.update(us_g=us_g, us_l=us_l)
        return 0.0, 0.0

    monkeypatch.setattr(hydraulics, "beggs_brill_dp", spy)
    fluid = Fluid(gas_mass_fraction=1e-3)
    path = geometry.PipePath(
        sections=[
            geometry.PipeSection(
                length=100.0, inclination=math.pi / 2, inner_diameter=0.2, roughness=1e-5
            )
        ]
    )
    stream = Stream(
        m_dot=Quantity(10.0, "kg/s"), T=Quantity(350.0, "K"), p=Quantity(2e6, "Pa"), fluid=fluid
    )
    hydraulics.pipe_path_profile(path, stream, fluid, "up", 0.0, 300.0)
    assert seen["us_g"] == pytest.approx(0.01 / 1.976 / (math.pi * 0.2**2 / 4), rel=1e-9)
