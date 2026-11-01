"""Judge a run against constraints of your own.

Shows ``gm.Constraint``, ``gm.Problem`` and ``gm.evaluate.constraints``. A violated constraint is
an answer, not an error. The constraints are assumptions of this recipe.

Run with ``python examples/recipes/check_limits.py``.
"""

import os
from pathlib import Path

import pandas as pd

import gemini as gm

INPUTS = Path(__file__).resolve().parents[2] / "inputs"
MONTH = INPUTS / "doublet_heat/doublet_2024_15min_month.csv"
DATA = Path(os.environ.get("GEMINI_EXAMPLE_DATASET", MONTH))


def problem(frame):
    """Return a problem with one constraint that holds and one that does not."""
    demand = gm.data.from_values([1.0] * len(frame), "W", "2024-07-01", "15 min", "heating_demand")
    constraints = [
        gm.Constraint(
            "injection_pump.discharge_pressure", max={"value": 60, "unit": "bar"}, when="running"
        ),
        gm.Constraint("heat_exchanger.duty", min={"value": 3.5, "unit": "MW"}, when="running"),
    ]
    return gm.Problem(demand, constraints=constraints)


def main():
    """Simulate the data and print each limit with the worst value of the run."""
    plant = gm.plants.example("DoubletHeatPlant")
    frame = pd.read_csv(DATA, parse_dates=["time"])
    results = gm.simulate(plant, plan=gm.Dataset.from_frame(frame, time_column="time"))
    print("Assumptions: at most 60 bar from the injection pump, at least 3.5 MW of heat")
    checks = gm.evaluate.constraints(plant, problem(frame), results)
    for check, unit in zip(checks, ("bar", "MW")):
        verdict = "ok" if check["passed"] else "VIOLATED"
        worst = gm.units.convert(check["value"].value, check["value"].unit, unit)
        print(f"{check['name']:<34} {verdict:<9} worst {worst:.2f} {unit}")


if __name__ == "__main__":
    main()
