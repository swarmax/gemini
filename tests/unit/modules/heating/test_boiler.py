"""First-law and zero-flow boiler limits."""

import pytest

import gemini as gm
from gemini.modules import GasGrid
from gemini.modules.heating import Boiler, ElectricBoiler
from gemini.physics import gas
from gemini.types.flows import Stream
from tests.fixtures.designs import with_values
from tests.fixtures.equivalence import assert_module_matches
from tests.fixtures.reading import reading

GRID_GAS = with_values(GasGrid())._offered()["gas_out"]
COPRODUCED = gm.Fluid(kind="gas", gas_composition={"CH4": 0.8, "CO2": 0.2})
WATER = Stream(
    m_dot=gm.units.Quantity(10, "kg/s"),
    T=gm.units.Quantity(300, "K"),
    p=gm.units.Quantity(1e6, "Pa"),
)


def test_capacity_balance_and_no_cooling():
    """Capacity caps heat, energy input accounts for efficiency, and the boiler never cools."""
    c = Boiler().set_params("", {"capacity": gm.units.Quantity(100000, "W"), "efficiency": 0.8})
    s = Stream(
        m_dot=gm.units.Quantity(10, "kg/s"),
        T=gm.units.Quantity(300, "K"),
        p=gm.units.Quantity(1e6, "Pa"),
    )
    result = c(temperature_setpoint=360, fluid_in=s, fuel_in=GRID_GAS)
    out, streams = reading(result), result.outlets
    assert out.is_capped and out.duty == pytest.approx(100000) and out.fuel == 125000
    assert (streams["fluid_out"].T - s.T) * s.m_dot * 4217.4 == pytest.approx(out.duty)
    assert streams["fluid_out"].m_dot == s.m_dot and streams["fluid_out"].p == s.p
    out = reading(c(temperature_setpoint=290, fluid_in=s, fuel_in=GRID_GAS))
    assert out.duty == 0 and out.fluid_out_T == 300
    out = reading(c(temperature_setpoint=360, fluid_in=s.with_(m_dot=0), fuel_in=GRID_GAS))
    assert out.duty == 0 and out.fluid_out_T == 300


def test_traced_call_matches_one_call_per_row():
    """Capped, uncapped, no-heating-needed and stopped rows trace and equal one call per row."""
    cases = [(10, 360), (1, 310), (10, 290), (0, 360), (2, 305)]
    gas = Boiler().set_params("", {"capacity": gm.units.Quantity(100000, "W"), "efficiency": 0.8})
    rows = [
        dict(
            fluid_in=Stream(
                m_dot=gm.units.Quantity(m, "kg/s"),
                T=gm.units.Quantity(300, "K"),
                p=gm.units.Quantity(1e6, "Pa"),
            ),
            fuel_in=GRID_GAS,
            temperature_setpoint=setpoint,
        )
        for m, setpoint in cases
    ]
    assert_module_matches(gas, rows)
    electric = ElectricBoiler().set_params(
        "", {"capacity": gm.units.Quantity(100000, "W"), "efficiency": 0.8}
    )
    rows = [
        dict(
            fluid_in=Stream(
                m_dot=gm.units.Quantity(m, "kg/s"),
                T=gm.units.Quantity(300, "K"),
                p=gm.units.Quantity(1e6, "Pa"),
            ),
            temperature_setpoint=setpoint,
        )
        for m, setpoint in cases
    ]
    assert_module_matches(electric, rows)


def gas_stream(flow, marked=True):
    """Return co-produced gas of ``flow`` [kg/s], on a stream with or without a grid connection."""
    fluid = COPRODUCED.with_grid(gas.GRID_COMPOSITION) if marked else COPRODUCED
    return Stream(
        m_dot=gm.units.Quantity(flow, "kg/s"),
        T=gm.units.Quantity(330, "K"),
        p=gm.units.Quantity(2e5, "Pa"),
        fluid=fluid,
    )


def test_co_produced_gas_is_burned_first_and_the_grid_covers_the_rest():
    """A boiler needs duty over efficiency; it burns what comes and buys the difference."""
    boiler = Boiler().set_params("", {"capacity": gm.units.Quantity(1e6, "W"), "efficiency": 0.8})
    heating_value = COPRODUCED.heating_value()
    available = 0.01 * heating_value
    offered = gas_stream(0.01)
    result = boiler(fluid_in=WATER, fuel_in=offered, temperature_setpoint=320)
    out = reading(result, offered)
    assert out.fuel == pytest.approx(out.duty / 0.8)
    assert out.fuel_coproduced == pytest.approx(available)
    assert out.fuel_purchased == pytest.approx(out.fuel - available)
    assert out.burned_mass_flow == pytest.approx(0.01)
    bought = out.fuel_purchased / gas.lower_heating_value(gas.GRID_COMPOSITION)
    assert result.inlets.fuel_in.m_dot == pytest.approx(0.01 + bought)
    expected = available * COPRODUCED.emission_factor()
    expected += out.fuel_purchased * gas.emission_per_energy(gas.GRID_COMPOSITION)
    assert result.outlets.flue_out.m_dot == pytest.approx(expected)


def test_enough_co_produced_gas_buys_nothing_and_takes_what_it_burns():
    """With gas to spare nothing is bought and ``fuel_in`` shows what it burned."""
    boiler = Boiler().set_params("", {"capacity": gm.units.Quantity(1e6, "W"), "efficiency": 0.8})
    offered = gas_stream(1.0)
    result = boiler(fluid_in=WATER, fuel_in=offered, temperature_setpoint=320)
    out = reading(result, offered)
    assert out.fuel_purchased == 0 and out.fuel_coproduced == pytest.approx(out.fuel)
    assert result.inlets.fuel_in.m_dot == pytest.approx(out.burned_mass_flow)


def test_no_co_produced_gas_buys_everything():
    """On a grid alone all fuel is bought and all its CO2 comes from the grid composition."""
    boiler = Boiler().set_params("", {"capacity": gm.units.Quantity(1e6, "W"), "efficiency": 0.8})
    result = boiler(fluid_in=WATER, fuel_in=GRID_GAS, temperature_setpoint=320)
    out = reading(result, GRID_GAS)
    assert out.fuel_coproduced == 0 and out.fuel_purchased == pytest.approx(out.fuel)
    assert result.outlets.flue_out.m_dot == pytest.approx(
        out.fuel * gas.emission_per_energy(gas.GRID_COMPOSITION)
    )


def test_without_a_grid_mark_the_gas_limits_the_duty():
    """A burner on an unmarked stream may not buy: the energy of the stream caps it."""
    boiler = Boiler().set_params("", {"capacity": gm.units.Quantity(1e6, "W"), "efficiency": 0.8})
    offered = gas_stream(0.002, False)
    result = boiler(fluid_in=WATER, fuel_in=offered, temperature_setpoint=360)
    out = reading(result, offered)
    assert out.fuel_purchased == pytest.approx(0, abs=1e-6) and out.is_capped
    assert out.duty == pytest.approx(0.002 * COPRODUCED.heating_value() * 0.8)


def test_an_electric_boiler_has_no_gas_ports():
    """Only the water side."""
    assert list(ElectricBoiler().inlets()) == ["fluid_in", "power_in"]
    assert list(ElectricBoiler().outlets()) == ["fluid_out", "loss_out"]
