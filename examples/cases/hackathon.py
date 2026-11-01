"""The hackathon case: two doublets, heat exchanger, heat pump, gas boiler and absorption chiller.

Simulates 2027 from the problem ``problem_with_treatment.json`` of the sample folder on the plant
dict ``plant_with_treatment.json``. The reservoir, brine, limits and supply temperatures are the
sample problem's; what this case assumes it prints as assumptions. Shows ``gm.Problem.from_json``,
``gm.Plant.from_json``, ``gm.simulate``, ``gm.evaluate.constraints``,
``gm.evaluate.plant_balance`` and ``gm.evaluate.totals``.

Run with ``python examples/cases/hackathon.py``.
"""

from pathlib import Path

import gemini as gm

MWH = 1000 * gm.units.convert(1, "kWh", "J")
GWH = 1000 * MWH
SAMPLE = Path(__file__).resolve().parents[2] / "inputs/examples/hackathon_2027"
"""The sample problem, read by this example only."""


ASSUMPTIONS = """Assumptions of this case, not of the sample problem:
  heating return 60 °C, cooling return 25 °C, chiller cooling water 15 °C
  air 10 °C; the chiller's dry cooler: 5 K approach, 2 % fan power
  20 mg/l sand, 90 % desander, 10 ppm inhibitor
  heat exchanger, heat pump, boiler and chiller sizes; 1000 m drainage radius
  discount rate, lifetime, every price and the cost factors without a source"""


def print_run(plant, problem, results):
    """Print the delivered energy, what remained unmet and the peaks, for daily steps."""
    frame = results.to_frame()
    gwh = 24.0 / 1e9
    gas = frame["gas_grid.gas_out.chemical_flow"]
    totals = gm.evaluate.totals(plant, problem, results)
    boiler = frame["boiler.fluid_out.enthalpy_flow"] - frame["boiler.fluid_in.enthalpy_flow"]
    sink = frame["heat_pump.sink_out.enthalpy_flow"] - frame["heat_pump.sink_in.enthalpy_flow"]
    rows = (
        ("heat delivered", totals["heat_delivered"].value / GWH, "GWh"),
        ("heat unmet", frame["heat_users.unmet_demand"].sum() * gwh, "GWh"),
        ("cold delivered", totals["cold_delivered"].value / GWH, "GWh"),
        ("cold unmet", frame["cool_users.unmet_sensible"].sum() * gwh, "GWh"),
        ("boiler, peak", boiler.max() / 1e6, "MW"),
        ("heat pump, peak", sink.max() / 1e6, "MW"),
        ("gas co-produced", (frame["boiler.fuel"] - gas).sum() * gwh, "GWh burnt"),
        ("gas purchased", gas.sum() * gwh, "GWh"),
        ("supply, lowest", frame["heat_users.supply_in.temperature"].min() - 273.15, "°C"),
    )
    print("\nThe year, in daily steps:")
    for label, value, unit in rows:
        print(f"  {label:<17} {value:8.2f} {unit}")


def print_constraints(checks):
    """Print each constraint of the sample problem, in its units."""
    print("\nConstraints:")
    for item in checks:
        value, unit = item["value"].value, item["value"].unit
        if unit == "m3/s":
            value, unit = gm.units.convert(value, unit, "m3/h"), "m³/h"
        if item["name"].endswith("temperature"):
            value, unit = gm.units.convert(value, unit, "degC"), "°C"
        result = "ok" if item["passed"] else "VIOLATED"
        print(f"  {item['name']:<33} {result:<9} worst {value:.4g} {unit}")


def print_balance(checks):
    """Print the plant balance: the root, and how many modules close."""
    modules = [item for item in checks if not item["name"].startswith("plant ")]
    closed = sum(item["passed"] is True for item in modules)
    print(f"\nBalance:\n  modules that close {closed} of {len(modules)}")
    for item in checks[-2:]:
        result = "ok" if item["passed"] else "OPEN"
        print(f"  {item['name']:<18} {result:<5} worst {item['value'].value:.3g}")


def print_totals(plant, problem, results):
    """Print what crossed the plant's edge and the KPIs of the run."""
    print("\nAt the plant's edge:")
    totals = gm.evaluate.totals(plant, problem, results)
    for name, item in totals.items():
        if item.unit in ("J", "kg"):
            scale, unit = (GWH, "GWh") if item.unit == "J" else (1e6, "kt")
            print(f"  {name:<20} {item.value / scale:10.3f} {unit}")
    print("\nKPIs:")
    for name, item in totals.items():
        if item.unit not in ("J", "kg"):
            scale, unit = (1e6, "MW") if item.unit == "W" else (1, "")
            print(f"  {name:<18} {item.value / scale:.4g} {unit}".rstrip())


def print_economics(plant, problem, results):
    """Print the economics in the units people read; every price is a placeholder."""
    totals = gm.evaluate.totals(plant, problem, results)
    heat, cold = totals["heat_delivered"].value, totals["cold_delivered"].value
    assumptions = problem.assumptions.to_dict() | {"heat_cost_share": heat / (heat + cold)}
    shared = gm.Problem(
        problem.demand, problem.site, problem.constraints, gm.Assumptions(**assumptions)
    )
    capex = gm.evaluate.capex(plant, shared)
    rows = (
        ("capex", capex.value / 1e6, f"MEUR ({capex.parts['price_year'].value})"),
        ("opex", gm.evaluate.opex(plant, shared, results).value / 1e6, "MEUR/year"),
        ("CO2-eq", gm.evaluate.co2(plant, shared, results).value / 1e6, "kt/year"),
        ("LCOH", gm.evaluate.lcoh(plant, shared, results).value * MWH, "EUR/MWh"),
        ("LCOC", gm.evaluate.lcoc(plant, shared, results).value * MWH, "EUR/MWh"),
        ("NPV", gm.evaluate.npv(plant, shared, results).value / 1e6, "MEUR"),
        ("payback", gm.evaluate.payback(plant, shared, results).value, "years"),
    )
    print("\nEconomics, on the placeholder prices above:")
    for label, value, unit in rows:
        print(f"  {label:<8} {value:8.2f} {unit}")


def main():
    """Simulate the year, then print what it delivered and what it costs."""
    problem = gm.Problem.from_json(SAMPLE / "problem_with_treatment.json")
    plant = gm.Plant.from_json(SAMPLE / "plant_with_treatment.json")
    print(ASSUMPTIONS)
    results = gm.simulate(plant, problem)
    print_run(plant, problem, results)
    print_constraints(gm.evaluate.constraints(plant, problem, results))
    print_balance(gm.evaluate.plant_balance(plant, problem, results))
    print_totals(plant, problem, results)
    print_economics(plant, problem, results)


if __name__ == "__main__":
    main()
