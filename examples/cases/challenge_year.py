"""The demand year on a sample plant: every requirement, checked on the run.

Plans 2027 for the plant dict ``plant.json`` of the sample problem, two doublets with a heat pump,
a boiler and three chillers, and simulates it. The reservoir, the brine, the limits and the supply
temperatures are the sample problem's; what this case assumes it prints as assumptions.

Shows ``gm.Problem.from_json``, ``gm.Plant.from_json``, ``gm.simulate``, ``gm.evaluate.totals``,
``gm.evaluate.constraints`` and ``gm.evaluate.lcts``.

Run with ``python examples/cases/challenge_year.py``.
"""

from pathlib import Path

import gemini as gm

MWH = 1000 * gm.units.convert(1, "kWh", "J")
GWH = 1000 * MWH
SAMPLE = Path(__file__).resolve().parents[2] / "inputs/examples/hackathon_2027"
"""The sample problem, read by this example only."""


ASSUMPTIONS = """Assumptions of this case, not of the sample problem:
  heating return 60 °C, cooling return 25 °C, air 10 °C all year
  well diameter 244 mm, 1000 m drainage radius, 30 bar at the injection pump
  heat exchanger, heat pump (15 MW), boiler (30 MW), absorption (7 MW), adsorption (1 MW) and
  compression (5 MW) sizes, in plant.json of the sample problem
  discount rate, lifetime, every price and the cost factors without a source"""


def print_year(plant, problem, results):
    """Print the energy of the year and the supply temperatures, in daily steps."""
    totals = gm.evaluate.totals(plant, problem, results)
    frame = results.to_frame()
    boiler = frame["peak_boiler.fluid_out.enthalpy_flow"]
    boiler = boiler - frame["peak_boiler.fluid_in.enthalpy_flow"]
    cold = frame["cooling_consumer.supply_in.mass_flow"] > 0
    rows = (
        ("heat delivered", totals["heat_delivered"].value / GWH, "GWh"),
        ("heat useful", totals["heat_useful"].value / GWH, "GWh"),
        ("heat surplus", totals["heat_surplus"].value / GWH, "GWh"),
        ("heat unmet", frame["heating_consumer.unmet_demand"].sum() * 86400 / GWH, "GWh"),
        ("cold delivered", totals["cold_delivered"].value / GWH, "GWh"),
        ("cold useful", totals["cold_useful"].value / GWH, "GWh"),
        ("cold surplus", totals["cold_surplus"].value / GWH, "GWh"),
        ("cold unmet", frame["cooling_consumer.unmet_sensible"].sum() * 86400 / GWH, "GWh"),
        ("boiler", boiler.sum() * 86400 / GWH, "GWh"),
        ("boiler, peak", boiler.max() / 1e6, "MW"),
        ("electricity", totals["electricity_bought"].value / GWH, "GWh"),
        ("gas bought", totals["gas_bought"].value / GWH, "GWh"),
        (
            "heating supply",
            frame["heating_consumer.supply_in.temperature"].min() - 273.15,
            "°C, lowest",
        ),
        (
            "cooling supply",
            frame["cooling_consumer.supply_in.temperature"][cold].max() - 273.15,
            "°C, warmest",
        ),
    )
    print("\nThe year, in daily steps:")
    for label, value, unit in rows:
        print(f"  {label:<15} {value:8.2f} {unit}")


def print_checks(checks):
    """Print each requirement: its verdict and the worst value of the run."""
    print("\nRequirements:")
    for item in checks:
        result = "ok" if item["passed"] else "VIOLATED"
        worst, unit = item["value"].value, item["value"].unit
        if unit == "m3/s" and "flow" in item["name"]:
            worst, unit = gm.units.convert(worst, unit, "m3/h"), "m³/h"
        if unit == "K" and item["name"].endswith("temperature"):
            worst, unit = gm.units.convert(worst, unit, "degC"), "°C"
        if unit == "s":
            worst, unit = worst / 86400, "day"
        print(f"  {item['name']:<39} {result:<9} worst {worst:.4g} {unit}")


def main():
    """Simulate the year of the sample problem, then print what it delivered and each constraint."""
    problem = gm.Problem.from_json(SAMPLE / "problem.json")
    plant = gm.Plant.from_json(SAMPLE / "plant.json")
    print(ASSUMPTIONS)
    results = gm.simulate(plant, problem, on_error="record")
    print(f"\nFailed days: {len(results.errors())}")
    print_year(plant, problem, results)
    print_checks(gm.evaluate.constraints(plant, problem, results))
    lcts = gm.evaluate.lcts(plant, problem, results)
    print(f"\nLCTS, on the placeholder prices above: {lcts.value * MWH:.2f} EUR/MWh")


if __name__ == "__main__":
    main()
