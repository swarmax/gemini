"""CO2 corrosion correlations: goldens, pinned bits, published references and input domain."""

import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from gemini import ops, units
from gemini.errors import PhysicsError, ValidationError
from gemini.physics import corrosion
from tests.fixtures.equivalence import assert_function_matches, assert_same_error
from tests.fixtures.errors import raises

GOLDEN = json.loads((Path(__file__).parents[2] / "fixtures/golden_values.json").read_text())

PINNED_CONDITIONS = dict(
    pressure=units.bar_to_pa(3),
    water_flow_rate=0.011574,
    water_density=1024,
    water_viscosity=5.469e-4,
    diameter=0.1778,
    roughness=2e-5,
    co2_fraction=0.1,
)


@pytest.mark.parametrize("name", [k for k in GOLDEN if k.startswith("corrosion_")])
def test_corrosion_golden(name):
    """All six SI correlation boundaries reproduce original unit-based results."""
    case = GOLDEN[name]
    u, p = case["inputs"], case["parameters"]
    actual = corrosion.co2_corrosion_rate(
        p["corrosion_model"],
        fitted=name.endswith("True"),
        temperature=units.c_to_k(u["temperature"]),
        pressure=units.bar_to_pa(u["pressure"]),
        water_flow_rate=u["flow_rate"],
        water_density=u["water_density"],
        water_viscosity=units.cp_to_pas(u["water_viscosity"]),
        diameter=p["diameter"],
        roughness=p["roughness"],
        co2_fraction=u["co2_fraction"],
        bicarb_concentration=u["bicarb_concentration"] / units.KILO,
        ionic_strength=u["ionic_strength"],
    )
    assert actual == pytest.approx(case["expected"]["corrosion_rate"], rel=1e-9, abs=0)


@pytest.mark.parametrize(
    "model,celsius,expected",
    [
        ("NORSOK", 5, "0x1.39ef6bb1d37b4p-4"),
        ("NORSOK", 39.999, "0x1.240fcd97dedbcp+4"),
        ("NORSOK", 40, "0x1.092d9caf59908p+0"),
        ("NORSOK", 40.001, "0x1.24124bce0d1e7p+4"),
        ("NORSOK", 50, "0x1.412a3d949fb8ap+4"),
        ("NORSOK", 90, "0x1.004aeaa323c4ap-3"),
        ("NORSOK", 150, "0x1.56035bc15bbccp+3"),
        ("NORSOK", 160, "0x1.561d97dafe0efp+3"),
        ("DLM", 5, "0x1.96c62ef6721c6p-3"),
        ("DLM", 40.001, "0x1.f01765ae47e6ep-1"),
        ("DLM", 160, "0x1.2216f8c7d8747p+2"),
        ("DLD", 5, "0x1.f3e05fdf33386p-2"),
        ("DLD", 40.001, "0x1.106aa3c5935dep-1"),
        ("DLD", 160, "0x1.0e5982cf02bb3p-4"),
    ],
)
def test_pinned_bits_on_and_off_the_temperature_table(model, celsius, expected):
    """Rates keep the exact bits of the original classes, including off-grid temperatures.

    NORSOK has a pH factor only at exactly tabulated temperatures (retained decision): the
    rate at 40 degC is about 1.04 mm/year and about 18.25 mm/year 0.001 degC either side.
    """
    for fitted in (False, True):
        rate = corrosion.co2_corrosion_rate(
            model, fitted=fitted, temperature=units.c_to_k(celsius), **PINNED_CONDITIONS
        )
        assert rate.hex() == expected


@pytest.mark.parametrize(
    "model,coefficients,expected",
    [
        ("NORSOK", {"A": 1.3}, "0x1.58bb4bb0c13bfp+0"),
        ("DLM", {"A": 5.5, "B": 1650, "C": 0.7}, "0x1.74ae0dfc24d21p-1"),
        ("DLD", {"A": 5.0, "B": 1100, "C": 0.6, "D": 2.0}, "0x1.c4ecafaf58582p-2"),
    ],
)
def test_fitted_coefficients_apply_only_to_fitted_models(model, coefficients, expected):
    """Fitted variants use supplied constants; published variants ignore them."""
    conditions = dict(PINNED_CONDITIONS, temperature=units.c_to_k(40), coefficients=coefficients)
    fitted = corrosion.co2_corrosion_rate(model, fitted=True, **conditions)
    published = corrosion.co2_corrosion_rate(model, **conditions)
    assert fitted.hex() == expected
    assert published == corrosion.co2_corrosion_rate(
        model, temperature=units.c_to_k(40), **PINNED_CONDITIONS
    )


@pytest.mark.parametrize("model,expected", [("DLM", 6.7), ("DLD", 9.6)])
@pytest.mark.parametrize("fitted", [False, True])
def test_original_reference(model, expected, fitted):
    """Retain the original tests at 50 degC and 3 bar (de Waard–Lotz 1991/1995)."""
    value = corrosion.co2_corrosion_rate(
        model,
        fitted=fitted,
        temperature=units.c_to_k(50),
        pressure=units.bar_to_pa(3),
        co2_fraction=1,
        water_flow_rate=math.pi * 0.1**2 / 4,
        diameter=0.1,
    )
    assert value == pytest.approx(expected, abs=0.05)


def test_partial_pressure_and_unknown_model():
    """Explicit CO2 partial pressure equals fraction times total pressure."""
    common = dict(temperature=313.15, pressure=300000, water_flow_rate=0.01)
    a = corrosion.co2_corrosion_rate("DLM", co2_fraction=0.1, **common)
    b = corrosion.co2_corrosion_rate("DLM", co2_partial_pressure=30000, **common)
    assert a == pytest.approx(b, rel=1e-12)
    with raises(ValidationError, "unknown_name", match="'NORSK'.*did you mean 'NORSOK'"):
        corrosion.co2_corrosion_rate("NORSK", co2_fraction=0.1, **common)
    with raises(PhysicsError, "missing_chemistry", match="co2_fraction"):
        corrosion.co2_corrosion_rate("DLM", **common)


@pytest.mark.parametrize("model", ["NORSOK", "DLD"])
def test_zero_flow_is_outside_flow_dependent_correlations(model):
    """NORSOK and DLD divide by the flow velocity; formerly ZeroDivisionError."""
    with pytest.raises(PhysicsError, match="water_flow_rate = 0"):
        corrosion.co2_corrosion_rate(
            model, temperature=330, pressure=3e5, water_flow_rate=0, co2_fraction=0.1
        )
    assert (
        corrosion.co2_corrosion_rate(
            "DLM", temperature=330, pressure=3e5, water_flow_rate=0, co2_fraction=0.1
        )
        > 0
    )


@pytest.mark.parametrize("model", ["NORSOK", "DLM", "DLD"])
@pytest.mark.parametrize("chemistry", [{"co2_fraction": 0}, {"co2_partial_pressure": 0}])
def test_zero_co2_is_outside_the_correlations(model, chemistry):
    """The correlations take the logarithm of the CO2 fugacity; formerly a math error."""
    with pytest.raises(PhysicsError, match="CO2 partial pressure = 0"):
        corrosion.co2_corrosion_rate(
            model, temperature=330, pressure=3e5, water_flow_rate=0.01, **chemistry
        )


def test_negative_flow_with_a_complex_rate_is_rejected():
    """A negative DLD velocity makes the rate complex; formerly TypeError from float()."""
    with pytest.raises(PhysicsError, match="complex rate"):
        corrosion.co2_corrosion_rate(
            "DLD", temperature=330, pressure=3e5, water_flow_rate=-0.01, co2_fraction=0.1
        )


def test_ph_factor_table_segments_and_fallback():
    """Tabulated segments include their upper bound; other temperatures and pH give 7."""
    assert corrosion._ph_factor(40.0, 4.6) == 2.0676 - 0.2309 * 4.6
    assert corrosion._ph_factor(5.0, 4.0) == 2.0676 + 0.2309 * 4.0
    assert corrosion._ph_factor(90.0, 5.62) == 21254 * math.exp(-2.1811 * 5.62)
    assert corrosion._ph_factor(150.0, 3.5) == 1
    assert corrosion._ph_factor(40.001, 5.0) == 7
    assert corrosion._ph_factor(40.0, 3.49) == 7
    assert corrosion._ph_factor(40.0, 6.51) == 7
    assert corrosion._ph_factor(40.0, float("nan")) == 7


def test_wall_loss():
    """WIMS integration uses interval duration and the original 365.25-day year."""
    np.testing.assert_allclose(
        corrosion.wall_loss([1, 2], [units.SECONDS_PER_YEAR / 2] * 2), [0.5, 1.5]
    )
    with pytest.raises(PhysicsError, match="shape"):
        corrosion.wall_loss([1, 2], [1])
    with pytest.raises(PhysicsError, match="negative"):
        corrosion.wall_loss([1], [-1])


def test_wims_remaining_wall_and_lifetime():
    """WIMS radial loss and linear lifetime retain deposition and missing-data limits."""
    assert corrosion.remaining_wall_thickness(0.1, 0.09, 0.002) == pytest.approx(0.008)
    assert corrosion.remaining_wall_thickness(0.1, 0.09, -0.002) == pytest.approx(0.012)
    assert corrosion.time_to_minimum_wall(0.008, 0.006, 1e-10) == pytest.approx(2e7)
    assert corrosion.time_to_minimum_wall(0.005, 0.006, 1e-10) == 0
    assert math.isinf(corrosion.time_to_minimum_wall(0.008, 0.006, 0))
    assert math.isnan(corrosion.time_to_minimum_wall(float("nan"), 0.006, 1e-10))


def _ph(temperature, pressure, ionic_strength, bicarb_concentration, co2_pressure):
    """Return the NORSOK pH of the conditions given as separate columns."""
    return corrosion._norsok_ph(
        SimpleNamespace(
            temperature=temperature,
            pressure=pressure,
            ionic_strength=ionic_strength,
            bicarb_concentration=bicarb_concentration,
            co2_pressure=co2_pressure,
        )
    )


PH_ROWS = [
    (60.0, 100.0, 10.0, 100.0, 1.0),
    (20.0, 3.0, 0.0, 1.0, 0.3),
    (120.0, 250.0, 80.0, 2500.0, 15.0),
    (40.0, 30.0, 5.0, 10.0, 25.0),
    (150.0, 400.0, 100.0, 0.5, 100.0),
    (
        26.131076070282795,
        443.6679871260469,
        36.9328387953744,
        -56680.8741604043,
        103.19760812153439,
    ),
    (60.0, 100.0, 10.0, math.nan, 1.0),
]


def test_norsok_ph_on_arrays_matches_floats_including_the_failed_root():
    """Both Newton starts, a nonpositive root and a NaN iteration agree on arrays and floats."""
    assert _ph(*PH_ROWS[5]) == 99.99 and _ph(*PH_ROWS[6]) == 99.99
    assert_function_matches(_ph, PH_ROWS)


def test_norsok_ph_on_a_dense_grid_has_no_rounding_boundary_flips():
    """The array Newton repeats the scalar stopping rule, so no pH moves by a rounding step."""
    generator = np.random.default_rng(3)
    columns = [
        generator.uniform(1, 160, 1500),
        generator.uniform(1, 300, 1500),
        generator.uniform(0, 150, 1500),
        generator.uniform(0.1, 3000, 1500),
        10 ** generator.uniform(-2, 2, 1500),
    ]
    expected = [_ph(*row) for row in zip(*(column.tolist() for column in columns))]
    np.testing.assert_allclose(_ph(*columns), expected, rtol=1e-12, atol=0)


def test_norsok_ph_underflow_raises_the_error_of_the_float_path():
    """Equilibrium constants that underflow raise on arrays with the same message."""
    rows = [(60.0, 100.0, 10.0, 100.0, 1.0), (60.0, 100.0, 1e5, 100.0, 1.0)]
    assert_same_error(_ph, rows, PhysicsError)


RATE_ROWS = [
    (278.15, 3e5, 0.011574),
    (313.15, 3e5, 0.02),
    (333.15, 5e6, 0.05),
    (350.0, 3e7, 0.011574),
    (420.0, 1e7, 0.003),
]


def _rate(model, **fixed):
    def rate(temperature, pressure, water_flow_rate):
        return corrosion.co2_corrosion_rate(
            model,
            temperature=temperature,
            pressure=pressure,
            water_flow_rate=water_flow_rate,
            **(dict(co2_fraction=0.1) | fixed),
        )

    return rate


@pytest.mark.parametrize("model", ["NORSOK", "DLM", "DLD"])
@pytest.mark.parametrize("chemistry", [{"co2_fraction": 0.1}, {"co2_partial_pressure": 40000}])
def test_co2_corrosion_rate_matches_arrays(model, chemistry):
    """Each correlation gives the same numbers on arrays as per row, with either CO2 input."""
    rate = _rate(model, **({"co2_fraction": None} | chemistry))
    assert_function_matches(rate, RATE_ROWS)


def test_fitted_coefficients_match_arrays():
    """Fitted DLD coefficients apply on arrays as on floats."""
    rate = _rate("DLD", fitted=True, coefficients={"A": 5.0, "D": 2.0})
    assert_function_matches(rate, RATE_ROWS)


@pytest.mark.parametrize("model", ["NORSOK", "DLM", "DLD"])
def test_zero_co2_error_matches_arrays(model):
    """Zero CO2 raises the same message on arrays as on floats."""
    assert_same_error(_rate(model, co2_fraction=0.0), RATE_ROWS, PhysicsError)


@pytest.mark.parametrize("model", ["NORSOK", "DLD"])
def test_flow_errors_match_arrays(model):
    """Zero flow raises the same message on arrays as on floats; DLD also rejects negative."""
    assert_same_error(_rate(model), RATE_ROWS[:2] + [(330.0, 3e5, 0.0)], PhysicsError)
    if model == "DLD":
        assert_same_error(_rate(model), RATE_ROWS[:2] + [(330.0, 3e5, -0.01)], PhysicsError)


def test_kt_and_ph_factor_match_arrays():
    """The interpolation and the exact-temperature pH table agree, with fallbacks and NaN."""
    temperatures = [5.0, 12.0, 15.0, 20.0, 40.0, 40.001, 75.0, 90.0, 150.0, 200.0, 0.0, math.nan]
    assert_function_matches(corrosion._kt, [(t,) for t in temperatures])
    rows = [(t, ph) for t in (5.0, 15.0, 90.0, 120.0, 150.0, 41.0) for ph in (3.4, 4.2, 5.3, 6.5)]
    assert_function_matches(corrosion._ph_factor, rows + [(40.0, math.nan), (60.0, 99.99)])


def test_wall_loss_and_lifetime_match_traced_semantics():
    """Wall loss accumulates as an array; lifetimes keep infinity and NaN on arrays."""
    year = units.SECONDS_PER_YEAR
    np.testing.assert_array_equal(
        corrosion.wall_loss(np.array([1.0, 2.0, -0.5]), np.array([year, year / 2, year])),
        np.cumsum(np.array([1.0, 1.0, -0.5])),
    )
    assert_function_matches(
        corrosion.time_to_minimum_wall,
        [
            (0.008, 0.006, 1e-10),
            (0.005, 0.006, 1e-10),
            (0.008, 0.006, 0.0),
            (0.008, 0.006, -1.0),
            (math.nan, 0.006, 1e-10),
            (0.008, 0.006, math.nan),
            (0.008, 0.006, math.inf),
        ],
    )
    assert_function_matches(
        corrosion.remaining_wall_thickness, [(0.1, 0.09, 0.002), (0.1, 0.09, -0.002)]
    )


@pytest.mark.parametrize("model", ["NORSOK", "DLM", "DLD"])
@pytest.mark.parametrize("cast", [float, int, np.float64])
def test_co2_corrosion_rate_returns_a_float(model, cast):
    """The outermost call gives a Python float whatever the numeric type of the inputs."""
    rate = corrosion.co2_corrosion_rate(
        model,
        temperature=cast(330),
        pressure=cast(300000),
        water_flow_rate=cast(1),
        co2_fraction=cast(1),
    )
    assert type(rate) is float


def test_a_stopped_row_drops_the_corrosion_errors():
    """Zero flow and zero CO2 on a stopped row do not fail the others: one function, one check."""

    @ops.physics
    def guarded(temperature, pressure, water_flow_rate):
        rate = corrosion.co2_corrosion_rate(
            "DLD",
            temperature=temperature,
            pressure=pressure,
            water_flow_rate=water_flow_rate,
            co2_fraction=0.1,
        )
        return ops.where(water_flow_rate == 0, 0.0, rate)

    rows = [(313.15, 3e5, 0.02), (330.0, 3e5, 0.0), (350.0, 3e7, 0.011574)]
    assert_function_matches(guarded, rows)


def test_time_to_minimum_wall_divides_by_a_zero_rate_silently():
    """A zero rate gives infinity for floats, ints and the traced run alike."""
    assert corrosion.time_to_minimum_wall(1.0, 0.5, 0.0) == math.inf
    assert corrosion.time_to_minimum_wall(1.0, 0.5, 0) == math.inf


def test_nan_input_passes_through_and_a_negative_flow_is_complex():
    """A NaN input gives a NaN rate, as before; a finite negative flow gives the complex error."""
    arguments = dict(temperature=333.15, pressure=1e7, co2_fraction=0.01)
    rate = corrosion.co2_corrosion_rate("DLD", water_flow_rate=float("nan"), **arguments)
    assert math.isnan(rate)
    with pytest.raises(PhysicsError, match="complex"):
        corrosion.co2_corrosion_rate("DLD", water_flow_rate=-1, **arguments)
