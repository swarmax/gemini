"""Write the generated schemas and every sample file of ``docs/schemas/``.

Run from the repository root after a change to a shape: ``python scripts/write_schemas.py``. The
schemas of the plant data and the profile come from ``gm.plants.schema()`` and
``gm.data.profile_schema()`` and those of the three return shapes from
``gemini.types.shapes``; the others are written by hand. The samples come from the example plant,
so other repositories can build against real documents.
"""

import json
from pathlib import Path

import pandas as pd

import gemini as gm
from gemini._utils import paths
from gemini._utils.jsonable import to_plain
from gemini.types import shapes

ROOT = Path(__file__).parents[1]
SCHEMAS = ROOT / "docs" / "schemas"
DATA = paths.doublet_heat("doublet_2024_15min_month.csv")
ROWS = 4
PROFILE = "heating_demand"
PROFILE_VALUES = [120.0, 135.5, 150.0, 142.5]


def _results(plant):
    """Return a replay of the first rows of the example data."""
    frame = pd.read_csv(DATA, parse_dates=["time"]).iloc[:ROWS]
    return gm.replay(plant, gm.Dataset.from_frame(frame, time_column="time"))


def _problem():
    """Return a problem on the made-up heating profile."""
    return gm.Problem(gm.data.from_values(PROFILE_VALUES, "kW", "2030-01-01", "1 h", PROFILE))


def _profile_sample():
    """Return a short heating profile of made-up values, in the document form of a profile."""
    frame = gm.data.from_values(PROFILE_VALUES, "kW", "2030-01-01", "1 h", PROFILE)
    return {
        "columns": {
            PROFILE: {
                "unit": frame.attrs["units"][PROFILE],
                "quantity": frame.attrs["quantities"][PROFILE],
            }
        },
        "time": [time.isoformat() for time in frame.index],
        "values": {PROFILE: frame[PROFILE].tolist()},
    }


def _problem_sample():
    """Return the problem of a real error."""
    try:
        gm.modules.get("Boilr")
    except gm.errors.GeminiError as error:
        return error.to_dict()
    raise gm.errors.ValidationError("gm.modules.get('Boilr') did not raise")


def documents():
    """Return ``{file name: document}`` of everything this script writes."""
    plant = gm.plants.example("DoubletHeatPlant")
    data = plant.to_dict(structure=True)
    results = _results(plant)
    return {
        "plant_dict.schema.json": gm.plants.schema(),
        "profile.schema.json": gm.data.profile_schema(),
        **{f"{name}.schema.json": schema for name, schema in shapes.SCHEMAS.items()},
        "module_description.sample.json": gm.plants.example("Doublet").describe(),
        "plant_dict.sample.json": data,
        "results_summary.sample.json": results.summary(),
        "profile.sample.json": _profile_sample(),
        "value.sample.json": results.summary()["heat_exchanger"]["duty"]["mean"],
        "problem.sample.json": _problem_sample(),
        "check.sample.json": to_plain(gm.evaluate.energy_balance(plant, _problem(), results)),
    }


def main():
    """Write every document with sorted keys."""
    for name, document in documents().items():
        text = json.dumps(document, indent=2, sort_keys=True, allow_nan=False)
        (SCHEMAS / name).write_text(text + "\n")


if __name__ == "__main__":
    main()
