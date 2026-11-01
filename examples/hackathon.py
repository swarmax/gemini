"""The hackathon flow on the 2027 case: size, minimise, simulate, check, report, compare.

Each candidate is sized, searched over the choices of the case on LCTS, simulated and reported; the
reports are compared on LCTS and CO2, the best gets a sensitivity table, and all are saved in
``.tmp/``. Shows ``gm.study.size``, ``minimize``, ``sensitivity`` and ``gm.evaluate.compare``.

Run with ``python examples/hackathon.py``.
"""

import json
from pathlib import Path

import gemini as gm

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "inputs/examples/hackathon_2027"
EVALUATIONS = 5
"""Simulations of the depth search for each doublet count."""
SHOWN = {"heat_delivered": "GWh", "cold_delivered": "GWh", "boiler_heat": "GWh", "co2": "kt"}
SHOWN |= {"capex": "MEUR", "opex": "MEUR/yr", "lcts": "EUR/MWh"}
Q = gm.units.Quantity
PARAMETERS = {
    "case.assumptions.finance.opex.electricity": {
        "low": Q(70, "EUR/MWh"),
        "high": Q(160, "EUR/MWh"),
    },
    "case.environment.reservoir.permeability": {"low": Q(150, "mD"), "high": Q(250, "mD")},
}


def design(plant, case):
    """Return the plant sized by gemini, then the best of the search over the case's choices."""
    sized = gm.study.size(plant, case)
    try:
        return gm.study.minimize(sized, case, "lcts", evaluations=EVALUATIONS)["best"]["plant"]
    except gm.errors.ValidationError as error:
        print(f"  not searched: {error.code}")
        return sized


def print_report(name, report):
    """Print what a candidate delivers, costs and fails."""
    failed = [item["name"] for item in report["constraints"] if not item["passed"]]
    print(f"{name}: failed steps {report['failed_steps']}, failed constraints {failed}")
    for key, unit in SHOWN.items():
        value = report[key].to(unit)
        print(f"  {key:<20} {value.reason or format(value.value, '10.2f')} {unit}")


def main():
    """Run the flow for every candidate and write the reports."""
    case = gm.Case.from_json(SAMPLE / "case.json")
    found = {}
    for path in sorted((SAMPLE / "plants").glob("*.json")):
        plant = design(gm.Plant.from_json(path), case)
        found[path.stem] = plant, gm.evaluate.report(plant, case, gm.simulate(plant, case))
        print_report(path.stem, found[path.stem][1])
    ranked = gm.evaluate.compare([report for _, report in found.values()], by=["lcts", "co2"])
    print(ranked.to_frame().to_string())
    print("Pareto front:", [name for name, item in zip(found, ranked) if item["pareto"]])
    best, _ = min(found.values(), key=lambda found: found[1]["lcts"].si)
    print(gm.study.sensitivity(best, case, PARAMETERS, ["lcts"]).to_frame().to_string())
    (ROOT / ".tmp").mkdir(exist_ok=True)
    for name, (_, report) in found.items():
        (ROOT / ".tmp" / f"{name}.json").write_text(json.dumps(report.to_dict(), indent=2))


if __name__ == "__main__":
    main()
