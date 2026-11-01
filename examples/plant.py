"""A plant dict built in Python, validated, saved with ``to_json`` and run on a case.

Starts from the plant dict of the shallow district sample, changes two sizes as plain values,
checks the plant, writes it to a temporary folder and runs it on the sample case.

Shows ``gm.Plant.from_dict``, ``validate``, ``to_json``, ``gm.Plant.from_json`` and ``gm.simulate``.

Run with ``python examples/plant.py``.
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import gemini as gm

SAMPLE = Path(__file__).resolve().parents[1] / "inputs/examples/shallow_district"


def build_dict():
    """Return the sample plant dict with a larger heat pump and a smaller boiler."""
    data = json.loads((SAMPLE / "plant.json").read_text())
    data["params"]["heat_pump.capacity"] = gm.units.Quantity(2.0, "MW").to_dict()
    data["params"]["peak_boiler.capacity"] = gm.units.Quantity(3.0, "MW").to_dict()
    return data


def main():
    """Build, validate and save the plant, load it again and run it on the sample case."""
    plant = gm.Plant.from_dict(build_dict())
    plant.validate()
    print(f"Modules: {len(plant.to_dict(structure=True)['modules'])}")
    with TemporaryDirectory() as folder:
        plant.to_json(Path(folder) / "plant.json")
        loaded = gm.Plant.from_json(Path(folder) / "plant.json")
    print(f"Same plant after the file: {loaded.to_dict() == plant.to_dict()}")
    case = gm.Case.from_json(SAMPLE / "case.json")
    report = gm.evaluate.report(loaded, case, gm.simulate(loaded, case))
    print(f"Heat from the boiler: {report['boiler_heat'].to('MWh').value:.1f} MWh")
    print(f"Heat delivered:       {report['heat_delivered'].to('MWh').value:.1f} MWh")


if __name__ == "__main__":
    main()
