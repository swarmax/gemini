"""``gm.case`` ground, reservoir, fluid, air and the two reservoir rules."""

import numpy as np
import pytest

import gemini as gm
from gemini.units import Quantity
from tests.fixtures.errors import raises


def environment():
    """Return an environment with ground, reservoir and fluid, the reservoir temperature absent."""
    return gm.case.Environment(
        ground=gm.case.Ground(
            surface_temperature=Quantity(12, "degC"), gradient=Quantity(30, "K/km")
        ),
        reservoir=gm.case.Reservoir(
            reference_depth=Quantity(2500, "m"), pressure=Quantity(250, "barg")
        ),
        fluid=gm.case.Fluid(density=Quantity(1030, "kg/m3"), gas={"CH4": 0.8, "CO2": 0.2}),
    )


def test_values_are_stored_in_si():
    """12 degC is 285.15 K, 250 barg an absolute pressure, 200 mD a permeability in m2."""
    case = environment()
    assert case.ground.surface_temperature == pytest.approx(285.15)
    assert case.reservoir.pressure == pytest.approx(250e5 + 101325)
    reservoir = gm.case.Reservoir(permeability=Quantity(200, "mD"))
    assert reservoir.permeability == pytest.approx(1.9738e-13, rel=1e-3)


def test_the_temperature_at_a_depth_follows_the_ground_without_a_given_temperature():
    """T = T_surface + gradient * depth: 87 degC at 2500 m."""
    assert environment().temperature_at(2500.0) == pytest.approx(285.15 + 75.0)


def test_a_given_reservoir_temperature_is_shifted_by_the_gradient():
    """The given value is the anchor at the reference depth, not the surface value."""
    given = environment().model_copy(
        update={
            "reservoir": gm.case.Reservoir(
                reference_depth=Quantity(2500, "m"), temperature=Quantity(90, "degC")
            )
        }
    )
    assert given.temperature_at(2500.0) == pytest.approx(363.15)
    assert given.temperature_at(3500.0) == pytest.approx(363.15 + 30.0)


def test_the_pressure_at_a_depth_adds_the_brine_column():
    """p(z) = p_ref + rho g (z - z_ref)."""
    case = environment()
    column = 1030 * 9.81 * 500.0
    assert case.pressure_at(3000.0) == pytest.approx(case.reservoir.pressure + column)
    assert case.pressure_at(2500.0) == pytest.approx(case.reservoir.pressure)


def test_a_rule_without_its_value_names_the_path():
    """An absent value is ``missing_value`` naming its path."""
    with raises(gm.errors.ValidationError, "missing_value") as caught:
        gm.case.Environment(ground=gm.case.Ground()).temperature_at(1000.0)
    assert "environment.ground.gradient" in str(caught.value)


def test_a_gas_is_known_species_that_sum_to_one():
    """The species are closed and the fractions sum to 1 within 1e-9."""
    assert gm.case.Fluid(gas={"CH4": 0.8, "CO2": 0.2}).gas == {"CH4": 0.8, "CO2": 0.2}
    with raises(gm.errors.ValidationError, "unknown_name"):
        gm.case.Fluid(gas={"O2": 1.0})
    with raises(gm.errors.ValidationError, "out_of_bounds"):
        gm.case.Fluid(gas={"CH4": 0.5})


def test_an_unknown_key_suggests_the_close_name():
    """The error names the section and the near key."""
    with raises(gm.errors.ValidationError, "unknown_name") as caught:
        gm.case.Reservoir(depth=Quantity(2500, "m"))
    assert "environment.reservoir" in str(caught.value) and "'reference_depth'" in str(caught.value)


def test_a_plain_number_with_a_dimension_is_refused():
    """Only a dimensionless value takes a plain number."""
    with raises(gm.errors.ValidationError, "invalid_value"):
        gm.case.Ground(gradient=0.03)
    assert gm.case.Fluid(gas_liquid_ratio=0.8).gas_liquid_ratio == 0.8


def test_the_air_is_a_constant_or_a_profile():
    """A profile is an array in K."""
    assert gm.case.Air(temperature=Quantity(10, "degC")).temperature == pytest.approx(283.15)
    air = gm.case.Air(temperature=Quantity([0.0, 10.0], "degC"))
    assert np.allclose(air.temperature, [273.15, 283.15])
    assert air.to_dict()["temperature"] == {"value": pytest.approx([273.15, 283.15]), "unit": "K"}


def test_a_profile_is_refused_where_a_value_is_one_number():
    """Only the air, prices and the CO2 intensity are profiles."""
    with raises(gm.errors.ValidationError, "invalid_value"):
        gm.case.Ground(gradient=Quantity([0.03, 0.03], "K/m"))
