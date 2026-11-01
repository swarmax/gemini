"""Plan a year of one doublet and a boiler from the heating demand, then simulate the plan.

Shows ``gm.data.from_csv``, ``gm.Problem``, ``gm.Constraint``, ``gm.schedule`` and ``gm.simulate``
on a small plant built from a doublet's depth. The doublet design, the sizes, the prices and the
return temperature are assumptions of this recipe and it prints them as such. The daily heating
demand is a file of the sample problem in ``inputs/examples/hackathon_2027/``; any file with a
time column and a demand column in a unit of power works the same, at any step.

Run with ``python examples/recipes/schedule_demand.py``.
"""

from pathlib import Path

import gemini as gm

DEMAND = Path(__file__).resolve().parents[2] / "inputs/examples/hackathon_2027"

BRINE = gm.Fluid(
    density={"value": 1030, "unit": "kg/m3"},
    viscosity={"value": 0.4, "unit": "mPa*s"},
    specific_heat={"value": 4000, "unit": "J/kg/K"},
)
DOUBLET = {
    "depth": {"value": 2500, "unit": "m"},
    "gradient": {"value": 30, "unit": "K/km"},
    "surface_temperature": {"value": 12, "unit": "degC"},
    "permeability": {"value": 200, "unit": "mD"},
    "thickness": {"value": 100, "unit": "m"},
    "well_diameter": {"value": 0.244, "unit": "m"},
    "nominal_flow": {"value": 300, "unit": "m3/h"},
    "pump_efficiency": 0.7,
    "nominal_wellhead_pressure": {"value": 10, "unit": "bar"},
}
EXCHANGER = {
    "thermal_conductance": {"value": 2000000, "unit": "W/K"},
    "hot_nominal_pressure_drop": {"value": 0, "unit": "bar"},
    "cold_nominal_pressure_drop": {"value": 0, "unit": "bar"},
    "hot_nominal_mass_flow": {"value": 85, "unit": "kg/s"},
    "cold_nominal_mass_flow": {"value": 85, "unit": "kg/s"},
}
CONSTRAINTS = [
    gm.Constraint(
        "d*.reservoir.liquid_flow",
        min={"value": 50, "unit": "m3/h"},
        max={"value": 300, "unit": "m3/h"},
        when="running",
    ),
    gm.Constraint("d*.brine_cooling", max={"value": 40, "unit": "K"}, when="running"),
]
PRICES = gm.Assumptions(
    prices={
        "electricity": {"value": 100, "unit": "EUR/MWh"},
        "gas": {"value": 40, "unit": "EUR/MWh"},
    }
)


def build():
    """Return a doublet, a heat exchanger and a boiler that serve a heating grid."""
    plant = gm.Plant("ScheduledHeat")
    plant.add("Doublet", name="d0", params=DOUBLET)
    plant.d0.fluid = BRINE
    plant.add("HeatExchanger", name="hx", params=EXCHANGER)
    plant.add(
        "Boiler", name="boiler", params={"capacity": {"value": 40, "unit": "MW"}, "efficiency": 0.9}
    )
    users = {
        "return_temperature": {"value": 60, "unit": "degC"},
        "return_pressure": {"value": 6, "unit": "bar"},
    }
    plant.add("HeatingGrid", name="users", params=users)
    plant.users.fluid = gm.WATER
    plant.add("GasGrid", name="gas")
    plant.add("ElectricityGrid", name="grid")
    plant.add("Atmosphere", name="air")
    plant.connect("d0.supply_out", "hx.hot_in")
    plant.connect("hx.hot_out", "d0.return_in")
    plant.connect("users.return_out", "hx.cold_in")
    plant.connect("hx.cold_out", "boiler.fluid_in")
    plant.connect("boiler.fluid_out", "users.supply_in")
    plant.connect("gas.gas_out", "boiler.fuel_in")
    plant.connect("grid.power_out", "d0.power_in")
    plant.connect("boiler.flue_out", "air.gas_in")
    plant.connect("boiler.loss_out", "air.heat_in")
    plant.boiler.temperature_setpoint = {"value": 100, "unit": "degC"}
    plant.air.temperature = {"value": 10, "unit": "degC"}
    return plant


def main():
    """Schedule the demand of a year, simulate the plan and print what it covers."""
    plant = build()
    print("Assumptions: a 2500 m doublet, 40 MW boiler, return at 60 °C, supply at 100 °C")
    print("             electricity at 100 EUR/MWh, gas at 40 EUR/MWh")
    columns = {"heating_demand_MWth": "heating_demand"}
    demand = gm.data.from_csv(DEMAND / "GEMINI_Heating_Demand_Daily_2027.csv", columns, "MW")
    problem = gm.Problem(demand, constraints=CONSTRAINTS, assumptions=PRICES)
    plan = gm.schedule(plant, problem)
    lowest = gm.units.convert(plan["d0.flow"].min(), "m3/s", "m3/h")
    highest = gm.units.convert(plan["d0.flow"].max(), "m3/s", "m3/h")
    print(f"Days planned:     {len(plan)}")
    print(f"Doublet flow:     {lowest:.0f} to {highest:.0f} m³/h")
    print(f"Boiler, peak:     {plan['boiler_duty'].max() / 1e6:.2f} MW")
    results = gm.simulate(plant, problem, plan=plan)
    totals = gm.evaluate.totals(plant, problem, results)
    print(f"Heat delivered:   {totals['heat_delivered'].value / 3.6e12:.2f} GWh")
    print(f"Gas bought:       {totals['gas_bought'].value / 3.6e12:.2f} GWh")
    print(f"Electricity:      {totals['electricity_bought'].value / 3.6e12:.2f} GWh")


if __name__ == "__main__":
    main()
