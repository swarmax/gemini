"""Costs of a design: capex per unit, opex, LCTS and CO2, and a missing assumption.

Runs the hackathon sample plant ``HeatingCoolingPlant`` for 2027 and reads its costs with
``gm.evaluate.capex``, ``opex``, ``lcts`` and ``co2``. Then it removes one capex factor from the
case and shows the ``missing_assumption`` error that names the factor. Shows ``gm.evaluate.capex``
and ``gm.errors.ValidationError``.

A limit on the electricity the plant buys is a constraint of the case, an assumption of 6 MW, and
``gm.evaluate.constraints`` checks it.

Run with ``python examples/costs.py``.
"""

from pathlib import Path

import gemini as gm

SAMPLE = Path(__file__).resolve().parents[1] / "inputs/examples/hackathon_2026"
MISSING = "heat_pump"
BOUGHT = {
    "on": "plant",
    "quantity": "electricity_bought",
    "over": "each",
    "max": {"value": 6, "unit": "MW"},
}
"""A limit of 6 MW on the electricity bought at any step, an assumption of this example."""


def show(label, quantity, unit):
    """Print one quantity in ``unit``."""
    value = quantity.to(unit)
    print(f"{label:<40} {value.value:12.2f} {value.unit}")


def print_costs(plant, case, results):
    """Print the capex of every unit, then the totals of a year."""
    capex = gm.evaluate.capex(plant, case)
    for path, item in capex.parts["modules"].items():
        show(f"capex {path} ({item.parts['kind']})", item, "MEUR")
    show("capex", capex, "MEUR")
    show("opex", gm.evaluate.opex(plant, case, results), "MEUR/yr")
    show("LCTS", gm.evaluate.lcts(plant, case, results), "EUR/MWh")
    show("CO2", gm.evaluate.co2(plant, case, results), "kt")


def print_bought(plant, case, results):
    """Add the limit on the electricity bought to the case and print its check."""
    data = case.to_dict()
    data["constraints"].append(BOUGHT)
    limited = gm.Case.from_dict(data, SAMPLE)
    for check in gm.evaluate.constraints(plant, limited, results):
        if check["role"] == "plant":
            value, limit = check["value"].to("MW"), check["limit"].to("MW")
            print(f"{check['name']}: {value.value:.3f} MW, limit {limit.value:.0f} MW")
            print(f"  passed: {check['passed']}")


def case_without(case, kind):
    """Return the case with the capex factor of ``kind`` removed."""
    data = case.to_dict()
    del data["assumptions"]["finance"]["capex"][kind]
    return gm.Case.from_dict(data, SAMPLE)


def print_missing(plant, case):
    """Ask for the capex without one factor and print the error."""
    try:
        gm.evaluate.capex(plant, case_without(case, MISSING))
    except gm.errors.ValidationError as error:
        print(f"{error.code}: {error.path}")


def main():
    """Cost the sample design, then show what a missing factor reports."""
    case = gm.Case.from_json(SAMPLE / "case.json")
    plant = gm.Plant.from_json(SAMPLE / "plants/HeatingCoolingPlant.json")
    results = gm.simulate(plant, case)
    print_costs(plant, case, results)
    print_bought(plant, case, results)
    print_missing(plant, case)


if __name__ == "__main__":
    main()
