"""Costs of a design: capex per unit, opex, LCTS and CO2, and a missing assumption.

Runs the hackathon sample plant ``HeatingCoolingPlant`` for 2027 and reads its costs with
``gm.evaluate.capex``, ``opex``, ``lcts`` and ``co2``. Then it removes one capex factor from the
case and shows the ``missing_assumption`` error that names the factor. Shows ``gm.evaluate.capex``
and ``gm.errors.ValidationError``.

Run with ``python examples/costs.py``.
"""

from pathlib import Path

import gemini as gm

SAMPLE = Path(__file__).resolve().parents[1] / "inputs/examples/hackathon_2027"
MISSING = "heat_pump"


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
    print_missing(plant, case)


if __name__ == "__main__":
    main()
