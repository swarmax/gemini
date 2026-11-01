"""The gas makeup: the co-produced gas first, the grid for the shortfall, the surplus out."""

import pytest

import gemini as gm
from gemini.modules import GasGrid, GasMakeup
from gemini.physics import gas
from tests.fixtures.designs import with_values
from tests.fixtures.equivalence import assert_module_matches

FLUID = gm.Fluid(kind="gas", gas_composition={"CH4": 0.8, "CO2": 0.2})
GAS = gm.Stream(
    m_dot=gm.units.Quantity(0.05, "kg/s"),
    T=gm.units.Quantity(330, "K"),
    p=gm.units.Quantity(2e5, "Pa"),
    fluid=FLUID,
)
GRID = with_values(GasGrid())._offered()["gas_out"]


def test_the_makeup_marks_the_offer_and_moves_no_gas():
    """Mass, temperature, pressure and composition stay in what it offers the burner."""
    outlet = GasMakeup()._offered({"gas_in": GAS, "grid_in": GRID})["fuel_out"]
    assert (outlet.m_dot, outlet.T, outlet.p) == (GAS.m_dot, GAS.T, GAS.p)
    assert outlet.fluid.gas_composition == FLUID.gas_composition
    assert outlet.fluid.grid_composition == gas.GRID_COMPOSITION


def test_the_surplus_leaves_through_excess_out():
    """A burner that burns less than the co-produced gas leaves the rest and draws no grid gas."""
    result = GasMakeup()(gas_in=GAS, grid_in=GRID, fuel_out=GAS.with_(m_dot=0.02))
    assert result.outlets.excess_out.m_dot == pytest.approx(0.03)
    assert result.inlets.grid_in.m_dot == 0


def test_the_shortfall_comes_from_the_grid():
    """A burner that burns more than the co-produced gas draws the rest and leaves no surplus."""
    result = GasMakeup()(gas_in=GAS, grid_in=GRID, fuel_out=GAS.with_(m_dot=0.08))
    assert result.outlets.excess_out.m_dot == 0
    assert result.inlets.grid_in.m_dot == pytest.approx(0.03)


def test_traced_calls_match_one_call_per_row():
    """The surplus and the shortfall trace, with the grid and the burner around the makeup."""
    plant = gm.Plant("Burner")
    plant.add("GasGrid", "grid")
    plant.add("GasMakeup", "makeup")
    plant.add("Boiler", "boiler", {"capacity": gm.units.Quantity(1e6, "W"), "efficiency": 0.9})
    plant.connect("gas_in", "makeup.gas_in")
    plant.connect("grid.gas_out", "makeup.grid_in")
    plant.connect("makeup.fuel_out", "boiler.fuel_in")
    plant.connect("makeup.excess_out", "excess")
    plant.connect("water_in", "boiler.fluid_in")
    plant.connect("boiler.fluid_out", "water_out")
    plant.connect("boiler.flue_out", "flue")
    plant.connect("boiler.loss_out", "loss")
    with_values(plant)
    plant.boiler.temperature_setpoint = 330.0
    water = gm.Stream(
        m_dot=gm.units.Quantity(5.0, "kg/s"),
        T=gm.units.Quantity(320.0, "K"),
        p=gm.units.Quantity(3e5, "Pa"),
        fluid=gm.WATER,
    )
    rows = [dict(gas_in=GAS.with_(m_dot=flow), water_in=water) for flow in (0.0, 0.1)]
    assert_module_matches(plant, rows)
