"""A plant built from its class: what it needs, fill it, size it, run it, see why steps failed.

Starts from the bare class ``HeatingHeatPumpCoolingPlant`` and asks ``missing_parameters`` what it
still needs. The design values of the shallow district sample stand in for the user's own
decisions; the sizes that ``size`` computes from the case are left out. ``size`` returns the plant
with notes on what it sized, what it left and what the sized design breaks. The plant then runs,
and ``failures`` groups the steps that failed.

Shows ``missing_parameters``, ``set_params``, ``gm.study.size`` with its ``sizing`` notes,
``gm.simulate`` and ``gm.evaluate.failures``.

Run with ``python examples/plant.py``.
"""

import json
from pathlib import Path

import gemini as gm

SAMPLE = Path(__file__).resolve().parents[1] / "inputs/examples/shallow_district"
SIZED = ("capacity", "nominal_flow", "nominal_head")
"""Name endings of the values ``size`` computes from the case."""
KEPT = "compression_cooler.capacity"
"""The cooler capacity, a design value ``size`` does not compute, so it stays."""
COOLER = Q = gm.units.Quantity(1.0, "MW")
"""The cooler capacity, the one size ``size`` leaves to the user, an assumption."""


def build(stored):
    """Return the plant class with the stored design values, except those ``size`` computes."""
    plant = gm.plants.HeatingHeatPumpCoolingPlant(doublets=stored["size"]["doublets"])
    missing = plant.missing_parameters()
    print(f"Bare class: {len(missing)} values missing, the first {missing[0]['path']}:")
    print(f"  {missing[0]['description']} [{missing[0]['unit']}]")
    designed = {
        key: value
        for key, value in stored["params"].items()
        if key == KEPT or not key.endswith(SIZED)
    }
    plant.set_params("", designed)
    plant.set_inputs(stored["inputs"])
    print(f"Filled: {len(plant.missing_parameters())} left: the reservoir and well the case gives, and the sizes")
    return plant


def main():
    """Fill the plant, size it, read the notes, simulate and group the failed steps."""
    stored = json.loads((SAMPLE / "plant.json").read_text())
    case = gm.Case.from_json(SAMPLE / "case.json")
    plant = build(stored)
    sized = gm.study.size(plant, case, backup="peak")
    for size in sized.sizing["sized"]:
        print(f"  sized {size['path']} = {size['value'].to_dict()}")
    print(f"Left unchanged: {[item['path'] for item in sized.sizing['unchanged']]}")
    print(f"Constraints broken by the start: {len(sized.sizing['broken'])}")
    print(f"Simulation of the start: {sized.sizing['simulation']}")
    results = gm.simulate(sized, case)
    print(f"Failed steps: {gm.evaluate.failures(results).to_dict()['total']}")
    report = gm.evaluate.report(sized, case, results)
    print(f"Heat delivered: {report['heat_delivered'].to('MWh').value:.1f} MWh")


if __name__ == "__main__":
    main()
