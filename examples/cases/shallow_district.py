"""Three winter weeks of a small district network on one shallow doublet.

Runs the hourly demand of the sample problem ``shallow_district`` for its plant dict
``plant.json``: one doublet at 1300 m, a heat pump and a boiler for a 65 °C network, and a small
compression chiller. The file names, the unit and the step differ from the challenge's. The values
are invented for testing; what this case assumes it prints as assumptions.

Shows ``gm.Problem.from_json``, ``gm.Plant.from_json``, ``gm.simulate`` and
``gm.evaluate.constraints``.

Run with ``python examples/cases/shallow_district.py``.
"""

from pathlib import Path

import gemini as gm

KWH = gm.units.convert(1, "kWh", "J")
SAMPLE = Path(__file__).resolve().parents[2] / "inputs/examples/shallow_district"
"""The sample problem, read by this example only."""
HOUR = 3600

ASSUMPTIONS = """Assumptions of this case, not of the sample problem:
  heating return 38 °C, cooling return 22 °C, air 6 °C all year
  well diameter 216 mm, 36 bar at the injection pump
  heat exchanger, heat pump (1.6 MW), boiler (3.5 MW) and chiller (0.4 MW) sizes, in plant.json
  of the sample problem"""


def print_run(plant, problem, results):
    """Print the energy of the run and the supply temperatures, in hourly steps."""
    totals = gm.evaluate.totals(plant, problem, results)
    frame = results.to_frame()
    boiler = frame["peak_boiler.fluid_out.enthalpy_flow"]
    boiler = boiler - frame["peak_boiler.fluid_in.enthalpy_flow"]
    cold = frame["cooling_consumer.supply_in.mass_flow"] > 0
    rows = (
        ("heat delivered", totals["heat_delivered"].value / KWH, "kWh"),
        ("heat unmet", frame["heating_consumer.unmet_demand"].sum() * HOUR / KWH, "kWh"),
        ("cold delivered", totals["cold_delivered"].value / KWH, "kWh"),
        ("cold unmet", frame["cooling_consumer.unmet_sensible"].sum() * HOUR / KWH, "kWh"),
        ("boiler", boiler.sum() * HOUR / KWH, "kWh"),
        ("boiler, peak", boiler.max() / 1e3, "kW"),
        ("electricity", totals["electricity_bought"].value / KWH, "kWh"),
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
    print("\nThe three weeks, in hourly steps:")
    for label, value, unit in rows:
        print(f"  {label:<15} {value:10.2f} {unit}")


def print_checks(checks):
    """Print each constraint: its verdict and the worst value of the run."""
    print("\nConstraints:")
    for item in checks:
        result = "ok" if item["passed"] else "VIOLATED"
        worst, unit = item["value"].value, item["value"].unit
        if unit == "m3/s" and "flow" in item["name"]:
            worst, unit = gm.units.convert(worst, unit, "m3/h"), "m³/h"
        if unit == "s":
            worst, unit = gm.units.convert(worst, unit, "h"), "h"
        if unit == "K" and item["name"].endswith("temperature"):
            worst, unit = gm.units.convert(worst, unit, "degC"), "°C"
        print(f"  {item['name']:<39} {result:<9} worst {worst:.4g} {unit}")


def main():
    """Simulate the three weeks, then print what they delivered and each constraint."""
    problem = gm.Problem.from_json(SAMPLE / "problem.json")
    plant = gm.Plant.from_json(SAMPLE / "plant.json")
    print(ASSUMPTIONS)
    results = gm.simulate(plant, problem, on_error="record")
    print(f"\nFailed hours: {len(results.errors())}")
    print_run(plant, problem, results)
    print_checks(gm.evaluate.constraints(plant, problem, results))


if __name__ == "__main__":
    main()
