"""Stream dtype identity, composition and reference property models."""

import numpy as np
import pytest
from pydantic import ValidationError as PydanticError
from pydantic_core import to_jsonable_python

import gemini as gm
from gemini.errors import ValidationError
from gemini.physics.fluid import FluidProperties
from gemini.types.flows import Stream
from gemini.types.fluid import BRINE, GLYCOL_30, STEAM, WATER, Fluid
from tests.fixtures.equivalence import assert_function_matches
from tests.fixtures.errors import raises


def _read(data):
    """Return the stream of the SI data a dump writes: stored data is not a public input."""
    return Stream._si(**{**data, "fluid": Fluid.model_validate(data["fluid"])})


def test_fluid_properties_and_identity():
    """Defaults preserve all legacy numbers; overrides travel with streams and cache safely."""
    assert BRINE.properties(1e5, 300) == FluidProperties()
    brine = Fluid(
        density=gm.units.Quantity(1068, "kg/m3"),
        viscosity=gm.units.Quantity(0.00065, "Pa.s"),
        co2_mass_fraction=0.01,
    )
    stream = Stream(
        m_dot=gm.units.Quantity(106.8, "kg/s"),
        p=gm.units.Quantity(1e5, "Pa"),
        T=gm.units.Quantity(300, "K"),
        fluid=brine,
    )
    assert stream.volumetric_flow() == pytest.approx(0.1)
    assert stream.with_(T=310).fluid == brine
    assert brine.properties(1e5, 300) is brine.properties(2e5, 350)
    assert WATER != BRINE
    assert GLYCOL_30.properties(1e5, 313.15) == FluidProperties(
        rho_l=1029.85, cp_l=3841, k_l=0.4622, mu_l=0.0016295
    )
    assert Fluid(gas_mass_fraction=0.1, specific_heat=gm.units.Quantity(4000, "J/kg/K")).properties(
        1e5, 300
    ) == (FluidProperties(gmf=0.1, cp_l=4000))
    assert _read(to_jsonable_python(stream)) == stream
    with pytest.raises(PydanticError):
        brine.salinity = 0.5
    with pytest.raises(gm.errors.ValidationError):
        Fluid(salinity=0.9, co2_mass_fraction=0.2)
    with raises(ValidationError, "invalid_call"):
        Stream(m_dot=1, T=300, p=1e5, fluid="brine")


def test_steam_kind_labels_vapour_without_changing_other_fluids():
    """``steam`` is a distinct, serialisable label; it keeps the default constant snapshot."""
    assert STEAM == Fluid(kind="steam") and STEAM not in (BRINE, WATER)
    assert STEAM.properties(6e5, 432) == FluidProperties()
    stream = Stream(
        m_dot=gm.units.Quantity(20, "kg/s"),
        T=gm.units.Quantity(432, "K"),
        p=gm.units.Quantity(6e5, "Pa"),
        fluid=STEAM,
    )
    assert _read(to_jsonable_python(stream)).fluid.kind == "steam"
    assert BRINE.kind == "brine" and WATER.kind == "water"


def test_corrosion_composition_conversion():
    """Dissolved mass fraction is converted through Henry law, never used as gas mole fraction."""
    from gemini.physics.chemistry import henry_constant

    fluid = Fluid(salinity=0.07, co2_mass_fraction=0.001, density=gm.units.Quantity(1068, "kg/m3"))
    values = fluid.corrosion_inputs(1e6, 300)
    assert values["ionic_strength"] == pytest.approx(74.76)
    assert values["co2_partial_pressure"] * henry_constant(300) == pytest.approx(1.068 / 0.04401)


def test_corrosion_inputs_on_arrays_match_floats():
    """The conversion works on arrays of pressure and temperature."""
    fluid = Fluid(salinity=0.07, co2_mass_fraction=0.001, density=gm.units.Quantity(1068, "kg/m3"))
    assert_function_matches(fluid.corrosion_inputs, [(1e6, 300.0), (2e6, 340.0), (5e5, 285.0)])
    values = fluid.corrosion_inputs(np.array([1e6, 2e6]), np.array([300.0, 340.0]))
    assert values["co2_partial_pressure"].shape == (2,)


DEGASSED_BRINE = dict(
    density={"value": 1030, "unit": "kg/m3"},
    viscosity={"value": 0.4, "unit": "mPa*s"},
    gas_liquid_ratio={"value": 0.8, "unit": "Nm3/m3"},
    gas_composition={"CH4": 0.8, "CO2": 0.2},
)


def test_a_brine_with_a_gas_ratio_derives_its_gas_mass_fraction():
    """Unit strings become SI; 0.8 Nm3/m3 of the 80/20 gas is 7.49e-4 of the mass."""
    brine = Fluid(**DEGASSED_BRINE)
    assert brine.density == 1030 and brine.viscosity == pytest.approx(4e-4)
    assert brine.normal_density() == pytest.approx(0.96534, abs=1e-4)
    assert brine.gas_mass_fraction == pytest.approx(7.4923e-4, rel=1e-3)
    assert brine.properties(1e5, 300).gmf == brine.gas_mass_fraction


def test_a_fluid_with_a_ratio_round_trips_and_hashes():
    """A dump leaves the derived fraction out and reads back; a composition has a hash."""
    brine = Fluid(**DEGASSED_BRINE)
    dumped = brine.model_dump(mode="json")
    assert "gas_mass_fraction" not in dumped
    again = Fluid.model_validate(dumped)
    assert again == brine and hash(again) == hash(brine)
    assert brine.properties(1e5, 300) is again.properties(1e5, 300)


@pytest.mark.parametrize(
    "fields",
    [
        dict(gas_liquid_ratio=0.8, gas_composition={"CH4": 1.0}, gas_mass_fraction=1e-3),
        dict(gas_liquid_ratio=0.8),
        dict(gas_composition={"CH4": 1.0}),
        dict(gas_liquid_ratio=0.8, gas_composition={"CH4": 0.5}),
        dict(gas_liquid_ratio=0.8, gas_composition={"H2": 1.0}),
        dict(kind="gas"),
    ],
    ids=["both", "no-composition", "no-ratio", "sum", "species", "gas-without-composition"],
)
def test_a_gas_description_that_does_not_fit_is_refused(fields):
    """Ratio with composition, or a mass fraction, never both; known species summing to one."""
    with pytest.raises(gm.errors.ValidationError):
        Fluid(**fields)


def test_a_gas_fluid_is_an_ideal_gas_of_its_composition():
    """Density follows the stream's pressure and temperature, also on arrays."""
    gas = Fluid(kind="gas", gas_composition={"CH4": 0.8, "CO2": 0.2})
    normal = gas.density_at(101325.0, 273.15)
    assert normal == pytest.approx(gas.normal_density())
    assert gas.density_at(202650.0, 273.15) == pytest.approx(2 * normal)
    stream = Stream(
        m_dot=gm.units.Quantity(1.0, "kg/s"),
        p=gm.units.Quantity(101325.0, "Pa"),
        T=gm.units.Quantity(273.15, "K"),
        fluid=gas,
    )
    assert stream.volumetric_flow() == pytest.approx(1 / normal)
    assert gas.density_at(np.array([101325.0, 202650.0]), 273.15)[1] == pytest.approx(2 * normal)
    assert Stream(
        flow={"value": 10, "unit": "m3/h"},
        p=gm.units.Quantity(101325.0, "Pa"),
        T=gm.units.Quantity(273.15, "K"),
        fluid=gas,
    ).m_dot == pytest.approx(10 / 3600 * normal)


def test_a_brine_with_a_composition_mixes_with_its_gas_at_the_stream_pressure():
    """The mixture is denser at depth; a flow in m3/h is the liquid volume at high pressure."""
    brine = Fluid(**DEGASSED_BRINE)
    deep, shallow = brine.density_at(200e5, 360.0), brine.density_at(5e5, 360.0)
    assert brine.gas_density_at(200e5, 360.0) == pytest.approx(144.6, abs=0.5)
    assert 1020 < deep < 1030 and shallow < deep
    assert brine.properties(1e5, 300).rho_g == pytest.approx(brine.normal_density())
    assert Stream(
        m_dot=gm.units.Quantity(1.0, "kg/s"),
        p=gm.units.Quantity(200e5, "Pa"),
        T=gm.units.Quantity(360.0, "K"),
        fluid=brine,
    ).volumetric_flow() == pytest.approx(1 / deep)


def test_a_property_in_a_unit_of_another_dimension_reports_invalid_unit():
    """The code of the unit error is kept, not turned into ``invalid_value``."""
    with raises(ValidationError, "invalid_unit", match="Fluid.density"):
        Fluid(density={"value": 1, "unit": "m3/h"})
