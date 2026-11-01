"""Turn a plant into a plant dict, build it back, and save and load it.

A plant of a class stores its class and its values; ``structure=True`` gives its modules and
connections, which is what an agent edits. Shows ``to_dict``, ``gm.Plant.from_dict``, ``save`` and
``gm.Plant.from_json``.

Run with ``python examples/basics/06_save_and_load.py``.
"""

from pathlib import Path
from tempfile import TemporaryDirectory

import gemini as gm


def main():
    """Round-trip a plant through a dictionary and through a file."""
    plant = gm.plants.example("DoubletHeatPlant")
    plant.set_params("heat_exchanger", {"thermal_conductance": {"value": 3500000, "unit": "W/K"}})
    data = plant.to_dict()
    print(f"Stored class:            {data['type']}")
    print(f"Stored values:           {len(data['params'])}")

    rebuilt = gm.Plant.from_dict(data)
    print(f"Same plant rebuilt:      {rebuilt.to_dict() == data}")

    structure = plant.to_dict(structure=True)
    print(f"Modules in the dict:     {len(structure['modules'])}")
    print(f"Connections in the dict: {len(structure['connections'])}")

    with TemporaryDirectory() as folder:
        path = Path(folder) / "plant.json"
        plant.to_json(path)
        loaded = gm.Plant.from_json(path)
    conductance = loaded.params_at("heat_exchanger")["thermal_conductance"]
    print(f"Conductance after load:  {conductance / 1e3:.0f} kW/K")
    print(f"Same plant loaded:       {loaded.to_dict() == data}")


if __name__ == "__main__":
    main()
