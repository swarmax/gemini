"""IAPWS-IF97 saturation, region 1 and region 2 properties and wet steam expansion."""

import math

import pytest

from gemini import ops
from gemini.errors import PhysicsError
from gemini.modules.power import _physics
from gemini.physics import heat_transfer
from tests.fixtures.equivalence import assert_function_matches, assert_same_error

IF97 = 1e-8
"""Relative tolerance for the nine-digit IAPWS-IF97 verification values."""


@pytest.mark.parametrize(
    ("temperature", "pressure"),
    [(300, 0.353658941e-2), (500, 0.263889776e1), (600, 0.123443146e2)],
)
def test_saturation_pressure_verification_values(temperature, pressure):
    """IF97 table 35: saturation pressure [MPa] at 300 K, 500 K and 600 K."""
    assert _physics.saturation_pressure(temperature) == pytest.approx(pressure * 1e6, rel=IF97)


@pytest.mark.parametrize(
    ("pressure", "temperature"),
    [(0.1, 0.372755919e3), (1, 0.453035632e3), (10, 0.584149488e3)],
)
def test_saturation_temperature_verification_values(pressure, temperature):
    """IF97 table 36: saturation temperature [K]; eqs. 30 and 31 invert each other."""
    assert _physics.saturation_temperature(pressure * 1e6) == pytest.approx(temperature, rel=IF97)
    round_trip = _physics.saturation_pressure(_physics.saturation_temperature(pressure * 1e6))
    assert round_trip == pytest.approx(pressure * 1e6, rel=1e-12)


@pytest.mark.parametrize(
    ("temperature", "pressure", "enthalpy", "entropy"),
    [
        (300, 3, 0.115331273e3, 0.392294792),
        (300, 80, 0.184142828e3, 0.368563852),
        (500, 3, 0.975542239e3, 0.258041912e1),
    ],
)
def test_region_1_verification_values(temperature, pressure, enthalpy, entropy):
    """IF97 table 5: liquid enthalpy [kJ/kg] and entropy [kJ/kg/K]."""
    p = pressure * 1e6
    assert _physics.liquid_enthalpy(p, temperature) == pytest.approx(enthalpy * 1e3, rel=IF97)
    assert _physics.liquid_entropy(p, temperature) == pytest.approx(entropy * 1e3, rel=IF97)


@pytest.mark.parametrize(
    ("temperature", "pressure", "enthalpy", "entropy"),
    [
        (300, 0.0035, 0.254991145e4, 0.852238967e1),
        (700, 0.0035, 0.333568375e4, 0.101749996e2),
        (700, 30, 0.263149474e4, 0.517540298e1),
    ],
)
def test_region_2_verification_values(temperature, pressure, enthalpy, entropy):
    """IF97 table 15: vapour enthalpy [kJ/kg] and entropy [kJ/kg/K]."""
    p = pressure * 1e6
    assert _physics.vapour_enthalpy(p, temperature) == pytest.approx(enthalpy * 1e3, rel=IF97)
    assert _physics.vapour_entropy(p, temperature) == pytest.approx(entropy * 1e3, rel=IF97)


def test_b23_boundary_and_saturation_table():
    """The B23 boundary meets the saturation line at 623.15 K; saturated states match tables.

    The saturated values at 0.1 MPa and 1 MPa are those of the IAPWS-IF97 steam tables
    (Wagner and Kretzschmar 2008, International Steam Tables, table 2) to five digits.
    """
    assert _physics.b23_pressure(623.15) == pytest.approx(0.165291643e8, rel=IF97)
    at_one_bar = _physics.saturation_properties(1e5)
    assert at_one_bar.temperature == pytest.approx(372.756, abs=1e-3)
    assert at_one_bar.liquid_enthalpy == pytest.approx(417.44e3, rel=1e-5)
    assert at_one_bar.vapour_enthalpy == pytest.approx(2674.95e3, rel=1e-5)
    assert at_one_bar.evaporation_enthalpy == pytest.approx(2257.51e3, rel=1e-5)
    assert at_one_bar.liquid_entropy == pytest.approx(1.30256e3, rel=1e-5)
    at_ten_bar = _physics.saturation_properties(1e6)
    assert at_ten_bar.vapour_enthalpy == pytest.approx(2777.12e3, rel=1e-5)
    assert at_ten_bar.evaporation_entropy == pytest.approx(6.58498e3 - 2.13843e3, rel=1e-5)


def test_domain_limits_raise():
    """States outside regions 1, 2 and 4 raise instead of extrapolating."""
    calls = [
        lambda: _physics.saturation_pressure(650),
        lambda: _physics.saturation_temperature(500),
        lambda: _physics.saturation_properties(17e6),
        lambda: _physics.liquid_enthalpy(1e5, 400),
        lambda: _physics.liquid_entropy(1e6, 630),
        lambda: _physics.vapour_enthalpy(1e6, 400),
        lambda: _physics.vapour_entropy(0, 400),
        lambda: _physics.vapour_enthalpy(40e6, 700),
        lambda: _physics.b23_pressure(900),
    ]
    for call in calls:
        with pytest.raises(PhysicsError):
            call()
    with pytest.raises(PhysicsError, match="saturation_pressure: temperature = nan"):
        _physics.saturation_pressure(float("nan"))


def test_saturated_states_lie_inside_both_regions():
    """Liquid and vapour exactly at saturation are accepted by the region checks."""
    for pressure in (0.01e6, 0.6e6, 16e6):
        temperature = _physics.saturation_temperature(pressure)
        saturation = _physics.saturation_properties(pressure)
        assert _physics.liquid_enthalpy(pressure, temperature) == saturation.liquid_enthalpy
        assert _physics.vapour_entropy(pressure, temperature) == saturation.vapour_entropy


def test_flash_fraction():
    """Flash fraction (h - h_f) / h_fg; subcooled liquid gives zero, vapour is rejected."""
    saturation = _physics.saturation_properties(6e5)
    half = saturation.liquid_enthalpy + 0.5 * saturation.evaporation_enthalpy
    assert _physics.flash_fraction(half, 6e5) == pytest.approx(0.5, rel=1e-12)
    assert _physics.flash_fraction(saturation.liquid_enthalpy - 1e3, 6e5) == 0
    with pytest.raises(PhysicsError, match="saturated vapour"):
        _physics.flash_fraction(saturation.vapour_enthalpy, 6e5)


def test_baumann_expansion_matches_dipippo_closed_form():
    """With a = 1 the exhaust enthalpy is DiPippo's eq. 5.13 with A = eta_d dh_s / 2."""
    expansion = _physics.baumann_expansion(6e5, 1e4, 0.85, 1)
    inlet, outlet = _physics.saturation_properties(6e5), _physics.saturation_properties(1e4)
    quality = (inlet.vapour_entropy - outlet.liquid_entropy) / outlet.evaporation_entropy
    h_s = outlet.liquid_enthalpy + quality * outlet.evaporation_enthalpy
    a = 0.425 * (inlet.vapour_enthalpy - h_s)
    h_out = (
        inlet.vapour_enthalpy - a * (1 - outlet.liquid_enthalpy / outlet.evaporation_enthalpy)
    ) / (1 + a / outlet.evaporation_enthalpy)
    assert expansion.outlet_enthalpy == pytest.approx(h_out, rel=1e-12)
    assert expansion.outlet_quality == pytest.approx(0.8678, abs=1e-4)
    assert expansion.efficiency == pytest.approx(0.85 * (1 + expansion.outlet_quality) / 2)


def test_baumann_expansion_limits():
    """No moisture penalty at a = 0; reversed pressures, bad inputs and a dry exhaust raise."""
    dry = _physics.baumann_expansion(6e5, 1e4, 0.85, 0)
    assert dry.efficiency == pytest.approx(0.85, rel=1e-12)
    for args in ((1e4, 6e5, 0.85, 1), (6e5, 1e4, 0, 1), (6e5, 1e4, 0.85, -1)):
        with pytest.raises(PhysicsError):
            _physics.baumann_expansion(*args)
    with pytest.raises(PhysicsError, match="wet exhaust"):
        _physics.baumann_expansion(6e5, 4e5, 0.2, 1)


def test_functions_match_on_arrays():
    """Every public function on arrays equals one call per row, across all region branches."""
    temperatures = [(300.0,), (500.0,), (600.0,), (640.0,)]
    assert_function_matches(_physics.saturation_pressure, temperatures)
    assert_function_matches(_physics.saturation_temperature, [(1e3,), (1e5,), (1e6,), (1.5e7,)])
    assert_function_matches(_physics.b23_pressure, [(623.15,), (700.0,), (863.15,)])
    liquid = [(3e6, 300.0), (8e7, 300.0), (3e6, 500.0), (1.7e7, 620.0)]
    assert_function_matches(_physics.liquid_enthalpy, liquid)
    assert_function_matches(_physics.liquid_entropy, liquid)
    vapour = [(3.5e3, 300.0), (1e5, 450.0), (1e6, 700.0), (3e7, 700.0), (3e7, 900.0)]
    assert_function_matches(_physics.vapour_enthalpy, vapour)
    assert_function_matches(_physics.vapour_entropy, vapour)
    assert_function_matches(_physics.saturation_properties, [(1e3,), (1e5,), (6e5,), (1.6e7,)])


def test_flash_and_expansion_match_on_arrays():
    """Flash fraction and Baumann expansion on arrays equal one call per row."""
    h_f = _physics.saturation_properties(6e5).liquid_enthalpy
    assert_function_matches(
        _physics.flash_fraction, [(h_f - 1e3, 6e5), (h_f + 4e5, 6e5), (1e6, 1e5), (2e6, 1e6)]
    )
    rows = [(6e5, 1e4, 0.85, 1.0), (6e5, 1e4, 0.85, 0.0), (1e6, 2e4, 0.7, 0.5)]
    assert_function_matches(_physics.baumann_expansion, rows)


@pytest.mark.parametrize(
    ("function", "rows"),
    [
        (_physics.saturation_pressure, [(300.0,), (650.0,)]),
        (_physics.saturation_temperature, [(1e5,), (500.0,)]),
        (_physics.b23_pressure, [(700.0,), (900.0,)]),
        (_physics.liquid_enthalpy, [(3e6, 300.0), (1e5, 400.0)]),
        (_physics.liquid_entropy, [(3e6, 300.0), (1e6, 630.0)]),
        (_physics.vapour_enthalpy, [(1e6, 700.0), (1e6, 400.0)]),
        (_physics.vapour_entropy, [(1e6, 700.0), (0.0, 400.0)]),
        (_physics.vapour_enthalpy, [(1e6, 700.0), (4e7, 700.0)]),
        (_physics.vapour_enthalpy, [(1e6, 700.0), (1e6, 1100.0)]),
        (_physics.saturation_properties, [(1e5,), (1.7e7,)]),
        (_physics.flash_fraction, [(1e6, 6e5), (3e6, 6e5)]),
        (_physics.baumann_expansion, [(6e5, 1e4, 0.85, 1.0), (1e4, 6e5, 0.85, 1.0)]),
        (_physics.baumann_expansion, [(6e5, 1e4, 0.85, 1.0), (6e5, 1e4, 0.0, 1.0)]),
        (_physics.baumann_expansion, [(6e5, 1e4, 0.85, 1.0), (6e5, 1e4, 0.85, -1.0)]),
        (_physics.baumann_expansion, [(6e5, 1e4, 0.85, 1.0), (6e5, 4e5, 0.2, 1.0)]),
    ],
)
def test_checks_match_on_arrays(function, rows):
    """A failing row raises the same error and message on arrays and on floats."""
    assert_same_error(function, rows, PhysicsError)


@ops.physics
def _vapour_enthalpy_when_wanted(wanted, pressure, temperature):
    """Return the steam enthalpy on the rows that want it and zero on the others."""
    return ops.where(wanted > 0, _physics.vapour_enthalpy(pressure, temperature), 0.0)


def test_the_range_error_of_an_unselected_row_is_dropped():
    """Rows that do not want steam give zero whatever their state; wanted rows still check."""
    rows = [(1.0, 5e5, 450.0), (1.0, 1e6, 700.0), (0.0, 1e6, 1100.0), (0.0, 4e7, 500.0)]
    assert_function_matches(_vapour_enthalpy_when_wanted, rows)
    assert_same_error(
        _vapour_enthalpy_when_wanted, [(1.0, 1e6, 700.0), (1.0, 4e7, 500.0)], PhysicsError
    )


def test_flash_state_splits_the_mass_flow():
    """Water at 450 K and 1 MPa flashed to 0.2 MPa: x = (h - h_f) / h_fg, masses add up."""
    state = _physics.flash_state(10.0, 450.0, 1e6, 2e5)
    saturation = _physics.saturation_properties(2e5)
    enthalpy = _physics.liquid_enthalpy(1e6, 450.0)
    fraction = (enthalpy - saturation.liquid_enthalpy) / saturation.evaporation_enthalpy
    assert state.steam_fraction == pytest.approx(fraction)
    assert state.steam_flow + state.liquid_flow == pytest.approx(10.0)
    assert state.liquid_temperature == pytest.approx(saturation.temperature)
    cold = _physics.flash_state(10.0, 350.0, 1e6, 2e5)
    assert (cold.steam_flow, cold.liquid_temperature) == (0, 350)


def test_flash_state_and_turbine_balance_match_on_arrays():
    """Flashing and subcooled rows, and the turbine balance, agree with the traced run."""
    assert_function_matches(
        _physics.flash_state, [(10.0, 450.0, 1e6), (5.0, 350.0, 1e6)], flash_pressure=2e5
    )
    assert_function_matches(
        _physics.turbine_balance,
        [(2.0, 2.7e6, 2.2e6, 3e5), (0.0, 2.7e6, 2.2e6, 3e5)],
        generator_efficiency=0.95,
    )


def test_turbine_balance_closes_the_first_law():
    """Inlet enthalpy flow equals electricity, heat loss and condensate enthalpy flow."""
    balance = _physics.turbine_balance(2.0, 2.7e6, 2.2e6, 3e5, 0.95)
    assert balance.gross_power == pytest.approx(1e6)
    assert balance.electricity_generated == pytest.approx(0.95e6)
    total = balance.electricity_generated + balance.heat_loss + 2.0 * 3e5
    assert total == pytest.approx(2.0 * 2.7e6)


DESIGN = dict(
    brine_heat_capacity=4200.0,
    ambient_temperature=285.0,
    condenser_approach=15.0,
    pinch=5.0,
    minimum_outlet_temperature=340.0,
    carnot_fraction=0.5,
    capacity=1e6,
)


def test_lorenz_efficiency_is_one_minus_condensing_over_log_mean():
    """The Lorenz efficiency equals 1 - T_c / T_lm for T_a = 400 K, T_b = 340 K, T_c = 300 K."""
    log_mean = (400 - 340) / math.log(400 / 340)
    assert _physics.lorenz_efficiency(400, 340, 300) == pytest.approx(1 - 300 / log_mean)


def test_cycle_design_caps_and_stops():
    """A large flow is capped at the capacity; a cold brine gives no power."""
    capped = _physics.cycle_design(400.0, 500.0, **DESIGN)
    assert capped.is_capped and capped.processed_share < 1
    cold = _physics.cycle_design(330.0, 10.0, **DESIGN)
    assert (cold.cycle_efficiency, cold.processed_share, cold.is_capped) == (0, 0, False)


def test_plant_balance_closes_the_first_law():
    """Heat input equals gross power plus condenser duty and net power plus heat loss."""
    balance = _physics.plant_balance(1000.0, 0.1, 0.2)
    assert balance.gross_power == pytest.approx(100)
    assert balance.electricity_generated == pytest.approx(80)
    assert balance.condenser_duty + balance.gross_power == pytest.approx(1000)
    assert balance.electricity_generated + balance.heat_loss == pytest.approx(1000)
    assert balance.thermal_efficiency == pytest.approx(0.08)


def test_brine_outlet_temperature_mixes_the_bypass():
    """Half the brine cooled from 400 K to 340 K gives 370 K."""
    assert heat_transfer.effectiveness_outlet_temperature(400, 0.5, 340) == pytest.approx(370)


def test_rows_match_arrays():
    """Design rows across running, capped and stopped agree with the traced run."""
    rows = [(400.0, 500.0), (400.0, 5.0), (330.0, 10.0)]
    assert_function_matches(_physics.cycle_design, rows, **DESIGN)
    assert_function_matches(_physics.lorenz_efficiency, [(400.0, 340.0, 300.0)])
    assert_function_matches(
        _physics.plant_balance, [(1000.0, 0.1), (0.0, 0.0)], parasitic_fraction=0.2
    )
    assert_function_matches(
        heat_transfer.effectiveness_outlet_temperature, [(400.0, 0.5, 340.0), (330.0, 0.0, 340.0)]
    )
