"""Doublet breakthrough, ground conduction shapes and Ramey wellbore relations."""

import math

import numpy as np
import pytest
from scipy.special import exp1

from gemini import ops
from gemini.errors import PhysicsError, ValidationError
from gemini.physics import ground
from tests.fixtures.equivalence import assert_function_matches, assert_same_error
from tests.fixtures.errors import raises


def test_aquifer_heat_capacity_and_breakthrough_volume():
    """The mixing rule weights by porosity; V_B is pi L**2 H (rho c)_a / (3 (rho c)_w)."""
    aquifer = ground.aquifer_volumetric_heat_capacity(0.2, 4.2e6, 2.5e6)
    assert aquifer == pytest.approx(0.2 * 4.2e6 + 0.8 * 2.5e6)
    volume = ground.doublet_breakthrough_volume(1000, 50, aquifer, 4.2e6)
    assert volume == pytest.approx(math.pi * 1000**2 * 50 * aquifer / (3 * 4.2e6))
    with pytest.raises(PhysicsError, match="porosity = 1.5"):
        ground.aquifer_volumetric_heat_capacity(1.5, 4.2e6, 2.5e6)
    with pytest.raises(PhysicsError, match="well_spacing = 0"):
        ground.doublet_breakthrough_volume(0, 50, aquifer, 4.2e6)


def test_doublet_cold_fraction_follows_the_dipole_travel_times():
    """No cold water before breakthrough; half the flow is cold at three breakthrough volumes."""
    assert ground.doublet_cold_fraction(0) == ground.doublet_cold_fraction(1) == 0
    assert ground.doublet_cold_fraction(3) == pytest.approx(0.5, abs=1e-12)
    theta = 1.0
    ratio = 3 * (math.sin(theta) - theta * math.cos(theta)) / math.sin(theta) ** 3
    assert ground.doublet_cold_fraction(ratio) == pytest.approx(theta / math.pi, abs=1e-12)
    small = 1 + 1e-8
    assert ground.doublet_cold_fraction(small) == pytest.approx(
        math.sqrt(5 * 1e-8 / 2) / math.pi, rel=1e-6
    )
    fractions = [ground.doublet_cold_fraction(r) for r in (1.01, 1.5, 4, 100, 1e6)]
    assert fractions == sorted(fractions) and fractions[-1] < 1
    assert ground.doublet_cold_fraction(1e300) == 1
    with pytest.raises(PhysicsError, match="volume_ratio = -1"):
        ground.doublet_cold_fraction(-1)


def test_series_and_direct_travel_times_agree_at_the_switch():
    """The small-angle series matches the closed form where the implementation switches."""
    theta = 0.1
    direct = 3 * (math.sin(theta) - theta * math.cos(theta)) / math.sin(theta) ** 3
    assert ground._dipole_travel_time(theta * (1 - 1e-12)) == pytest.approx(direct, rel=1e-12)


def test_store_and_field_conductances():
    """The store conductance uses its whole envelope; the field uses the cylinder shape factor."""
    radius = math.sqrt(1e5 / (math.pi * 20))
    area = 2 * math.pi * radius * (radius + 20)
    expected = 2 * 2.5 * area / math.sqrt(math.pi * 1e-6 * 1.5e7)
    assert ground.cylinder_store_conductance(2.5, 1e-6, 1e5, 20, 1.5e7) == pytest.approx(expected)
    assert ground.cylinder_store_conductance(2.5, 1e-6, 0, 20, 1.5e7) == 0
    assert ground.vertical_cylinder_conductance(2, 150, 20) == pytest.approx(
        2 * 2 * math.pi * 150 / math.log(30)
    )
    with pytest.raises(PhysicsError, match="volume = -1"):
        ground.cylinder_store_conductance(2.5, 1e-6, -1, 20, 1.5e7)
    with pytest.raises(PhysicsError, match="expected ln"):
        ground.vertical_cylinder_conductance(2, 10, 40)


def test_steady_flux_resistance_matches_the_annulus_solution():
    """The closed form equals the integrated uniform-sink annulus profile and Hellstrom's limit."""
    k, r_b, r_e, sink = 2.0, 0.075, 3.0, 1.0
    r = np.linspace(r_b, r_e, 200001)
    rise = sink / (2 * k) * (r_e**2 * np.log(r / r_b) - (r**2 - r_b**2) / 2)
    weights = 2 * np.pi * r
    mean = np.sum((rise[1:] * weights[1:] + rise[:-1] * weights[:-1]) / 2 * np.diff(r))
    mean /= np.pi * (r_e**2 - r_b**2)
    heat = sink * np.pi * (r_e**2 - r_b**2)
    assert ground.steady_flux_resistance(k, r_b, r_e) == pytest.approx(mean / heat, rel=1e-8)
    limit = (math.log(1e4) - 0.75) / (2 * math.pi * k)
    assert ground.steady_flux_resistance(k, 1e-4, 1) == pytest.approx(limit, rel=1e-7)
    with pytest.raises(PhysicsError, match="cell_radius = 0.05"):
        ground.steady_flux_resistance(k, r_b, 0.05)


def test_ramey_time_function_is_the_line_source_asymptote():
    """At long times f(t) equals half the exponential integral; short times are rejected."""
    time, diffusivity, radius = 3.15e7, 1e-6, 0.1
    exact = exp1(radius**2 / (4 * diffusivity * time)) / 2
    assert ground.ramey_time_function(time, diffusivity, radius) == pytest.approx(exact, rel=1e-4)
    fourier = ground.MIN_RAMEY_FOURIER
    short = ground.ramey_time_function(fourier * radius**2 / diffusivity, diffusivity, radius)
    assert short == pytest.approx(exp1(1 / (4 * fourier)) / 2, rel=0.01)
    with pytest.raises(PhysicsError, match="alpha t / r"):
        ground.ramey_time_function(3600, diffusivity, radius)
    with pytest.raises(PhysicsError, match="time = 0"):
        ground.ramey_time_function(0, diffusivity, radius)


def test_ramey_fluid_temperature_solves_the_energy_balance():
    """The profile satisfies dT/dz = (T_rock - T) / A and starts at the inlet temperature."""
    args = dict(inlet_temperature=300, top_temperature=283, gradient=0.03, relaxation_length=800)
    assert ground.ramey_fluid_temperature(length=0, **args) == 300
    depth, step = 1500.0, 1e-3
    slope = (
        ground.ramey_fluid_temperature(length=depth + step, **args)
        - ground.ramey_fluid_temperature(length=depth - step, **args)
    ) / (2 * step)
    temperature = ground.ramey_fluid_temperature(length=depth, **args)
    assert slope == pytest.approx((283 + 0.03 * depth - temperature) / 800, rel=1e-6)
    far = ground.ramey_fluid_temperature(length=1e6, **args)
    assert far == pytest.approx(283 + 0.03 * 1e6 - 0.03 * 800)
    with pytest.raises(PhysicsError, match="length = -1"):
        ground.ramey_fluid_temperature(length=-1, **args)
    with pytest.raises(PhysicsError, match="relaxation_length = 0"):
        ground.ramey_fluid_temperature(**(args | {"relaxation_length": 0}), length=10)


COLD_FRACTION_RATIOS = [(0.0,), (0.5,), (1.0,), (1.0000001,), (1.01,), (3.0,), (100.0,), (1e8,)]


def test_doublet_cold_fraction_on_arrays_matches_floats_on_every_branch():
    """Before breakthrough, on the decline and past the last streamline agree on arrays."""
    assert_function_matches(ground.doublet_cold_fraction, COLD_FRACTION_RATIOS)
    assert_function_matches(ground.doublet_cold_fraction, [(1e300,), (math.inf,), (2.0,)])


def test_doublet_cold_fraction_on_a_dense_grid():
    """The angle solve matches the scalar one over six decades of the volume ratio."""
    ratios = np.concatenate([np.linspace(1.0, 5.0, 400), np.geomspace(1.0001, 1e6, 400)])
    expected = [ground.doublet_cold_fraction(ratio) for ratio in ratios.tolist()]
    np.testing.assert_allclose(ground.doublet_cold_fraction(ratios), expected, rtol=1e-12, atol=0)


@pytest.mark.parametrize("rows", [[(2.0,), (-1.0,)], [(math.nan,)]])
def test_doublet_cold_fraction_rows_raise_the_error_of_the_float_path(rows):
    """A negative or NaN ratio raises the same class and message on arrays."""
    assert_same_error(ground.doublet_cold_fraction, rows, PhysicsError)


def test_aquifer_and_breakthrough_match_on_arrays():
    """The mixing rule and the breakthrough volume agree on arrays; bad inputs raise alike."""
    rows = [(0.2, 4.2e6, 2.5e6), (0.0, 4.2e6, 2.5e6), (1.0, 3e6, 2e6)]
    assert_function_matches(ground.aquifer_volumetric_heat_capacity, rows)
    assert_same_error(
        ground.aquifer_volumetric_heat_capacity, rows + [(1.5, 4.2e6, 2.5e6)], PhysicsError
    )
    assert_same_error(
        ground.aquifer_volumetric_heat_capacity, rows + [(0.2, 0.0, 2.5e6)], PhysicsError
    )
    rows = [(1000.0, 50.0, 3.0e6, 4.2e6), (500.0, 20.0, 2.8e6, 4.0e6)]
    assert_function_matches(ground.doublet_breakthrough_volume, rows)
    assert_same_error(
        ground.doublet_breakthrough_volume, rows + [(0.0, 50.0, 3.0e6, 4.2e6)], PhysicsError
    )


def test_store_and_field_conductances_match_on_arrays():
    """Store, vertical cylinder and borehole cell relations agree on arrays and raise alike."""
    rows = [(2.0, 1e-6, 5e4, 40.0, 1.5e7), (1.5, 8e-7, 0.0, 20.0, 3e7)]
    assert_function_matches(ground.cylinder_store_conductance, rows)
    assert_same_error(
        ground.cylinder_store_conductance,
        rows + [(2.0, 1e-6, -1.0, 40.0, 1.5e7)],
        PhysicsError,
    )
    rows = [(2.0, 100.0, 0.15), (1.7, 50.0, 0.3)]
    assert_function_matches(ground.vertical_cylinder_conductance, rows)
    assert_same_error(ground.vertical_cylinder_conductance, rows + [(2.0, 0.1, 0.15)], PhysicsError)
    rows = [(2.0, 0.075, 3.0), (1.5, 0.05, 0.2)]
    assert_function_matches(ground.steady_flux_resistance, rows)
    assert_same_error(ground.steady_flux_resistance, rows + [(2.0, 0.075, 0.05)], PhysicsError)


def test_ramey_relations_match_on_arrays():
    """Ramey's time function and fluid profile agree on arrays and raise alike."""
    rows = [(3e7, 1e-6, 0.1), (1e9, 1.2e-6, 0.15)]
    assert_function_matches(ground.ramey_time_function, rows)
    assert_same_error(ground.ramey_time_function, rows + [(10.0, 1e-6, 0.1)], PhysicsError)
    rows = [(300.0, 283.0, 0.03, 1500.0, 800.0), (320.0, 283.0, -0.01, 0.0, 400.0)]
    assert_function_matches(ground.ramey_fluid_temperature, rows)
    assert_same_error(
        ground.ramey_fluid_temperature,
        rows + [(300.0, 283.0, 0.03, -1.0, 800.0)],
        PhysicsError,
    )


def test_a_failing_check_is_dropped_by_the_branch_that_does_not_select_it():
    """Rows with a zero or too early time take the fallback, with no safe input, on arrays too."""

    @ops.physics
    def after_start(time, diffusivity, radius):
        late = time >= 1e5
        return ops.where(late, ground.ramey_time_function(time, diffusivity, radius), -1.0)

    rows = [(3e7, 1e-6, 0.1), (0.0, 1e-6, 0.1), (10.0, 1e-6, 0.1), (1e9, 1.2e-6, 0.15)]
    assert_function_matches(after_start, rows)
    assert after_start(0.0, 1e-6, 0.1) == -1.0


def test_ground_relations_raise_the_error_class_of_their_caller():
    """The context prefix and error class name the module that rejects its own configuration."""
    with raises(
        ValidationError, "invalid_design", match="^field: borehole cell: steady_flux_resistance"
    ):
        ground.steady_flux_resistance(
            2.0,
            0.075,
            0.05,
            error=ValidationError,
            code="invalid_design",
            context="field: borehole cell: ",
        )
    with raises(
        ValidationError, "invalid_design", match="^field: shape: vertical_cylinder_conductance"
    ):
        ground.vertical_cylinder_conductance(
            2.0, 10.0, 40.0, error=ValidationError, code="invalid_design", context="field: shape: "
        )
    with raises(ValidationError, "invalid_design", match="^well: ramey_time_function: time = 0"):
        ground.ramey_time_function(
            0.0, 1e-6, 0.1, error=ValidationError, code="invalid_design", context="well: "
        )


def test_doublet_drop_and_time_by_hand():
    """No drop before breakthrough; half the contrast at three breakthrough volumes."""
    assert ground.injected_volume(0.02, 3600) == pytest.approx(72.0)
    assert ground.doublet_temperature_drop(10, 100, 370, 300) == 0
    assert ground.doublet_temperature_drop(300, 100, 370, 300) == pytest.approx(35, abs=1e-9)
    assert ground.doublet_breakthrough_time(1000, 0.5) == 2000
    assert ground.doublet_breakthrough_time(1000, 0) is None
    rows = [(10.0, 100.0, 370.0, 300.0), (300.0, 100.0, 370.0, 300.0), (1e5, 100.0, 370.0, 300.0)]
    assert_function_matches(ground.doublet_temperature_drop, rows)
    assert_function_matches(ground.doublet_breakthrough_time, [(1000.0, 0.5), (1000.0, 0.0)])
    assert_function_matches(ground.injected_volume, [(0.02, 3600.0), (0.0, 1.0)])


def test_aquifer_store_relations_by_hand():
    """Mixing weights by volume, an empty store keeps no excess, conduction decays exactly."""
    assert ground.mix_store(100, 10, 100, 0) == (200, 5)
    assert ground.mix_store(100, 10, 0, 0) == (100, 10)
    assert ground.stored_heat(4e6, 10, 5) == 2e8
    assert ground.aquifer_stored_energy(4e6, 10, 5, 20, -2) == 4e6 * (50 - 40)
    assert ground.thermal_recovery(1.0, 4.0) == 0.25
    assert ground.thermal_recovery(1.0, 0.0) is None
    assert ground.store_relaxation(8.0, 0.0, 0.0, 10.0, 4e6) == 0
    assert ground.store_relaxation(8.0, 1.0, 4e6, 1.0, 4e6) == pytest.approx(8.0 / math.e)
    assert ground.store_conductance(1e5, 2.0, 0.2, 4.2e6, 2.5e6, 50, 1.5e7) == pytest.approx(
        ground.cylinder_store_conductance(
            2.0, 2.0 / (0.2 * 4.2e6 + 0.8 * 2.5e6), 1e5 * 4.2e6 / 2.84e6, 50, 1.5e7
        )
    )


def test_aquifer_store_relations_match_on_arrays():
    """Every branch of the mixing, decay and recovery relations agrees on arrays."""
    assert_function_matches(ground.mix_store, [(100.0, 10.0, 100.0, 0.0), (100.0, 10.0, 0.0, 3.0)])
    assert_function_matches(
        ground.store_relaxation,
        [(8.0, 0.0, 1e3, 10.0, 4e6), (8.0, 1e5, 1e3, 1e5, 4e6), (-3.0, 2e5, 0.0, 10.0, 4e6)],
    )
    assert_function_matches(ground.thermal_recovery, [(1.0, 4.0), (1.0, 0.0), (1.0, -1.0)])
    assert_function_matches(ground.stored_heat, [(4e6, 10.0, 5.0)])
    assert_function_matches(ground.aquifer_stored_energy, [(4e6, 10.0, 5.0, 20.0, -2.0)])
    assert_function_matches(
        ground.store_conductance,
        [(0.0, 2.0, 0.2, 4.2e6, 2.5e6, 50.0, 1.5e7), (1e5, 2.0, 0.2, 4.2e6, 2.5e6, 50.0, 1.5e7)],
    )


BOREHOLE = (100.0, 150.0, 0.075, 6.0, 2.0, 0.1)


def test_borehole_field_relations_by_hand():
    """Conductance of the loops, surroundings and capacity follow their closed forms."""
    cell = ground.steady_flux_resistance(2.0, 0.075, 6.0 / math.sqrt(math.pi))
    unit = 100 * 150 / (0.1 + cell)
    expected = -math.expm1(-unit / 30.0) * 30.0
    assert ground.borehole_loop_conductance(30.0, *BOREHOLE) == pytest.approx(expected)
    assert ground.borehole_loop_conductance(0.0, *BOREHOLE) == 0
    diameter = 2 * math.sqrt(100 * 36 / math.pi)
    assert ground.borehole_field_surroundings_conductance(100, 6.0, 150.0, 2.0) == pytest.approx(
        ground.vertical_cylinder_conductance(2.0, 150.0, diameter)
    )
    assert ground.borehole_field_capacity(2.2e6, 100, 6.0, 150.0) == 2.2e6 * 100 * 36 * 150
    far = ground.borehole_field_temperature_change(0.0, 50.0, 10.0, 290.0, 283.0, 1e12, 1e12)
    assert far == pytest.approx(50.0 * 7.0 / 60.0, rel=1e-3)
    assert ground.borehole_field_temperature_change(2.0, 50.0, 10.0, 283.0, 283.0, 0.0, 1e9) == 2.0


def test_borehole_field_relations_match_on_arrays():
    """Stopped and flowing loops, and the step update, agree on arrays."""
    assert_function_matches(
        ground.borehole_loop_conductance,
        [(30.0, *BOREHOLE), (1e3, *BOREHOLE), (0.0, *BOREHOLE)],
    )
    assert_function_matches(
        ground.borehole_field_surroundings_conductance, [(100.0, 6.0, 150.0, 2.0)]
    )
    assert_function_matches(ground.borehole_field_capacity, [(2.2e6, 100.0, 6.0, 150.0)])
    assert_function_matches(
        ground.borehole_field_temperature_change,
        [(0.0, 50.0, 10.0, 290.0, 283.0, 3600.0, 1e12), (2.0, 0.0, 10.0, 283.0, 283.0, 1e5, 1e9)],
    )


def test_ramey_resistance_and_relaxation_length_by_hand():
    """R_r = f / (2 pi k) and A = m cp (R_b + R_r)."""
    function = ground.ramey_time_function(1e7, 1e-6, 0.1)
    resistance = ground.ramey_rock_resistance(1e7, 1e-6, 0.1, 2.5)
    assert resistance == pytest.approx(function / (2 * math.pi * 2.5))
    assert ground.ramey_relaxation_length(20.0, 0.1, 0.3) == pytest.approx(8.0)
    assert_function_matches(
        ground.ramey_rock_resistance, [(1e7, 1e-6, 0.1, 2.5), (1e9, 1e-6, 0.1, 3.0)]
    )
    assert_function_matches(ground.ramey_relaxation_length, [(20.0, 0.1, 0.3), (0.0, 0.1, 0.3)])


def test_geotherm_temperature_is_linear_in_depth():
    """12 degC at 30 K/km is 87 degC at 2 500 m."""
    assert ground.geotherm_temperature(285.15, 0.03, 2500.0) == pytest.approx(360.15)
    assert_function_matches(
        ground.geotherm_temperature, [(285.15, 0.03, 2500.0), (280.0, 0.0, 0.0)]
    )


def test_reservoir_temperature_anchors_a_given_temperature_or_follows_the_surface():
    """Without a reference temperature T = T_s + g z; with one T = T_ref + g (z - z_ref)."""
    assert ground.reservoir_temperature(285.15, 0.03, 2500.0, 2500.0) == pytest.approx(360.15)
    assert ground.reservoir_temperature(None, 0.03, 3500.0, 2500.0, 363.15) == pytest.approx(393.15)
    assert ground.reservoir_temperature(None, 0.03, 2000.0, 2500.0, 363.15) == pytest.approx(348.15)


def test_reservoir_pressure_adds_the_brine_column_from_the_reference_depth():
    """Pressure is p_ref + rho g (z - z_ref), above and below the reference."""
    reference = 251.0e5
    assert ground.reservoir_pressure(reference, 1030.0, 3000.0, 2500.0) == pytest.approx(
        reference + 1030.0 * 9.81 * 500.0
    )
    assert ground.reservoir_pressure(reference, 1030.0, 2500.0, 2500.0) == reference
    assert ground.reservoir_pressure(reference, 1030.0, 2000.0, 2500.0) < reference
