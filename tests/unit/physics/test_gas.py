"""A gas from its composition: densities, heating value, CO2 and the gas-liquid ratio."""

import pytest

from gemini.physics import combustion, constants, gas
from tests.fixtures.equivalence import assert_function_matches

METHANE = {"CH4": 1.0}
PRODUCED = {"CH4": 0.8, "CO2": 0.2}


def test_molar_mass_is_the_mole_weighted_sum():
    """80 % CH4 and 20 % CO2 weigh 21.636 g/mol."""
    assert gas.molar_mass(METHANE) == pytest.approx(float(combustion.METHANE_MOLAR_MASS))
    assert gas.molar_mass(PRODUCED) == pytest.approx(0.0216364, rel=1e-5)


def test_ideal_gas_density():
    """Methane at normal conditions is 0.7158 kg/m3 as an ideal gas."""
    assert gas.ideal_gas_density(101325.0, 273.15, 0.016043) == pytest.approx(0.7158, abs=1e-3)
    rows = [(101325.0, 273.15, 0.016043), (2e5, 300.0, 0.0216364)]
    assert_function_matches(gas.ideal_gas_density, rows)


def test_normal_density_of_the_produced_gas():
    """A gas of 80 % CH4 and 20 % CO2 by mole is about 0.97 kg/Nm3."""
    assert gas.normal_density(PRODUCED) == pytest.approx(0.9653, abs=1e-3)


def test_the_reference_conditions_of_a_normal_density_are_arguments():
    """DIN 1343 normal conditions by default; the ISO 13443 standard ones, 15 degC, on request."""
    assert gas.normal_density(PRODUCED) == gas.normal_density(PRODUCED, 273.15, 101325.0)
    standard = gas.normal_density(PRODUCED, 288.15, 101325.0)
    assert standard == pytest.approx(gas.normal_density(PRODUCED) * 273.15 / 288.15)


def test_heating_value_of_methane_is_the_constant_of_combustion():
    """802.3 kJ/mol over 16.043 g/mol is the 50 MJ/kg of the existing flare constant."""
    assert gas.lower_heating_value(METHANE) == pytest.approx(combustion.METHANE_HEATING_VALUE, 1e-3)
    assert gas.lower_heating_value({"CO2": 0.5, "N2": 0.5}) == 0


def test_combustion_co2_counts_burnt_carbon_only():
    """A mole of methane forms a mole of CO2; the CO2 carried in the gas is not formed."""
    assert gas.combustion_co2(METHANE) == pytest.approx(
        float(constants.CO2_MOLAR_MASS) / float(combustion.METHANE_MOLAR_MASS)
    )
    assert gas.combustion_co2({"CO2": 1.0}) == 0
    assert gas.mass_fraction({"CO2": 1.0}, "CO2") == 1
    assert gas.mass_fraction(PRODUCED, "CO2") == pytest.approx(0.2 * 0.04401 / 0.0216364, 1e-4)
    assert gas.mass_fraction(PRODUCED, "N2") == 0


def test_grid_gas_agrees_with_its_published_analysis():
    """The lumped default keeps the published molar mass and CO2 factor within 1 %."""
    composition = gas.GRID_COMPOSITION
    assert sum(composition.values()) == pytest.approx(1)
    assert gas.molar_mass(composition) == pytest.approx(0.0187155, rel=1e-2)
    factor = gas.combustion_co2(composition) / gas.lower_heating_value(composition)
    assert factor + gas.mass_fraction(composition, "CO2") / gas.lower_heating_value(
        composition
    ) == pytest.approx(56.474e-9, rel=1e-2)


def test_the_gas_liquid_ratio_and_the_mass_fraction_are_inverses():
    """0.8 Nm3/m3 of a 0.9653 kg/Nm3 gas in 1030 kg/m3 brine is 7.49e-4 of the mass."""
    fraction = gas.gas_mass_fraction(0.8, 0.9653, 1030.0)
    assert fraction == pytest.approx(7.492e-4, rel=1e-3)
    assert gas.gas_liquid_ratio(fraction, 0.9653, 1030.0) == pytest.approx(0.8)
    rows = [(0.8, 0.9653, 1030.0), (0.0, 0.9653, 1030.0)]
    assert_function_matches(gas.gas_mass_fraction, rows)
    assert_function_matches(gas.gas_liquid_ratio, [(7.49e-4, 0.9653, 1030.0), (0.0, 0.9, 1000.0)])


def test_species_flow_without_composition_is_zero_for_any_flow():
    """No composition gives zero, also for an infinite or NaN flow."""
    assert gas.species_flow(float("inf"), None, "CO2") == 0.0
    assert gas.species_flow(float("nan"), None, "CO2") == 0.0
