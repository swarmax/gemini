"""Gas-engine CHP: fuel, power and heat at full and part load, heat dumping and closure."""

import pytest

from gemini.errors import PhysicsError, ValidationError
from gemini.modules import GasGrid
from gemini.modules._utils.balance import energy_balance, mass_balance
from gemini.modules.heating import CHP
from gemini.physics import gas
from gemini.types.flows import Stream
from gemini.types.fluid import Fluid
from gemini.units import Quantity
from tests.fixtures import si
from tests.fixtures.designs import with_values
from tests.fixtures.equivalence import assert_module_matches
from tests.fixtures.errors import raises
from tests.fixtures.reading import reading

CP = 4217.4
WATER = Stream(m_dot=Quantity(20, "kg/s"), T=Quantity(333.15, "K"), p=Quantity(3e5, "Pa"))
GRID_GAS = with_values(GasGrid())._offered()["gas_out"]


def engine(**params):
    """Return a 1 MW engine with 40 % electric and 45 % thermal efficiency, 90 degC limit."""
    design = dict(
        electric_capacity=1e6,
        electric_efficiency=0.4,
        thermal_efficiency=0.45,
        maximum_outlet_temperature=363.15,
    )
    return si.set_params(CHP(), "", design | params)


def test_full_load_hand_value_and_closure():
    """Full load burns 2.5 MW, recovers 1.125 MW and loses the remaining 0.375 MW."""
    unit = engine()
    result = unit(fluid_in=WATER, fuel_in=GRID_GAS, load_fraction=1)
    out = reading(result)
    assert out.fuel == pytest.approx(2.5e6) and out.electricity_generated == 1e6
    assert out.heat_recovered == pytest.approx(1.125e6) and out.dumped_heat == 0
    assert out.heat_loss == pytest.approx(0.375e6)
    assert out.fluid_out_T == pytest.approx(WATER.T + 1.125e6 / (20 * CP))
    assert result.outlets.fluid_out.p == WATER.p
    assert energy_balance(unit, result)["relative_residual"] < 1e-12
    assert mass_balance(unit, result)["residual"] == 0


def test_part_load_willans_line():
    """With a no-load fuel share the electric efficiency falls at part load."""
    unit = engine(no_load_fuel_fraction=0.1)
    result = unit(fluid_in=WATER, fuel_in=GRID_GAS, load_fraction=0.5)
    out = reading(result)
    assert out.fuel == pytest.approx(2.5e6 * (0.1 + 0.9 * 0.5))
    assert out.electricity_generated / out.fuel == pytest.approx(0.4 * 0.5 / 0.55)
    assert out.heat_recovered == pytest.approx(0.45 * out.fuel)
    assert energy_balance(unit, result)["relative_residual"] < 1e-12
    constant = reading(engine()(fluid_in=WATER, fuel_in=GRID_GAS, load_fraction=0.5))
    assert constant.electricity_generated / constant.fuel == pytest.approx(0.4)


def test_heat_dumping_and_engine_off():
    """Heat above the outlet limit or without flow is dumped; zero load burns nothing."""
    small = WATER.with_(m_dot=2)
    out = reading(engine()(fluid_in=small, fuel_in=GRID_GAS, load_fraction=1))
    assert out.fluid_out_T == pytest.approx(363.15)
    assert out.heat_recovered == pytest.approx(2 * CP * 30)
    assert out.dumped_heat == pytest.approx(1.125e6 - 2 * CP * 30)
    unit = engine()
    result = unit(fluid_in=WATER.with_(m_dot=0), fuel_in=GRID_GAS, load_fraction=1)
    assert reading(result).heat_recovered == 0 and reading(result).heat_loss == pytest.approx(1.5e6)
    assert energy_balance(unit, result)["relative_residual"] < 1e-12
    off = reading(engine()(fluid_in=WATER, fuel_in=GRID_GAS, load_fraction=0))
    assert off.fuel == off.heat_loss == off.electricity_generated == 0
    assert off.fluid_out_T == WATER.T


def test_invalid_design_and_flow_raise():
    """Efficiencies above one in sum and reversed flow raise the documented errors."""
    with raises(
        ValidationError, "invalid_design", match="electric_efficiency \\+ thermal_efficiency"
    ):
        engine(thermal_efficiency=0.7)(fluid_in=WATER, fuel_in=GRID_GAS, load_fraction=1)
    with pytest.raises(PhysicsError, match="fluid_in.m_dot = -1"):
        engine()(fluid_in=WATER.with_(m_dot=-1), fuel_in=GRID_GAS, load_fraction=1)


def test_traced_call_matches_one_call_per_row():
    """Off, part load, full load, dumping and stopped-water rows trace and equal per-row calls."""
    unit = engine(no_load_fuel_fraction=0.1)
    rows = [
        dict(
            fluid_in=Stream(
                m_dot=Quantity(m_dot, "kg/s"), T=Quantity(T, "K"), p=Quantity(3e5, "Pa")
            ),
            fuel_in=GRID_GAS,
            load_fraction=load,
        )
        for m_dot, T, load in [
            (20, 333.15, 1),
            (20, 333.15, 0.5),
            (20, 333.15, 0),
            (2, 333.15, 1),
            (0, 333.15, 1),
            (20, 370, 1),
        ]
    ]
    assert_module_matches(unit, rows)


def test_an_engine_on_co_produced_gas_buys_what_it_lacks():
    """Co-produced gas comes first, as in a boiler; the rest is purchased."""
    fluid = Fluid(kind="gas", gas_composition={"CH4": 1.0}).with_grid(gas.GRID_COMPOSITION)
    fuel = Stream(
        m_dot=Quantity(0.01, "kg/s"), T=Quantity(330, "K"), p=Quantity(2e5, "Pa"), fluid=fluid
    )
    out = reading(engine()(fluid_in=WATER, fuel_in=fuel, load_fraction=1), fuel)
    assert out.fuel == pytest.approx(2.5e6)
    assert out.fuel_coproduced == pytest.approx(0.01 * fluid.heating_value())
    assert out.fuel_purchased == pytest.approx(out.fuel - out.fuel_coproduced)


def test_an_engine_without_a_grid_mark_is_limited_by_its_gas():
    """On an unmarked stream the gas sets the load."""
    fluid = Fluid(kind="gas", gas_composition={"CH4": 1.0})
    fuel = Stream(
        m_dot=Quantity(0.01, "kg/s"), T=Quantity(330, "K"), p=Quantity(2e5, "Pa"), fluid=fluid
    )
    out = reading(engine()(fluid_in=WATER, fuel_in=fuel, load_fraction=1), fuel)
    assert out.fuel_purchased == 0
    assert out.fuel == pytest.approx(0.01 * fluid.heating_value())
