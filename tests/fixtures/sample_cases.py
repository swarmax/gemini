"""The sample cases of ``inputs/examples/``: only examples and tests read them."""

import json

import gemini as gm
from gemini._utils import paths, registry
from gemini._utils.files import from_json
from gemini.modules._utils.serialization import Report, from_sections
from gemini.plants._utils import reader
from gemini.run._utils.apply import apply_case

HACKATHON_2026 = paths.INPUTS / "examples/hackathon_2026"
SHALLOW_DISTRICT = paths.INPUTS / "examples/shallow_district"
SAMPLE_PLANT = "HeatingCoolingPlant"
"""The class of the main candidate; every candidate is in ``plants/``."""
TEMPLATES = (
    "HeatingPlant",
    "HeatingAbsorptionCoolingPlant",
    "HeatingHeatPumpCoolingPlant",
    "HeatingFullCoolingPlant",
)


def sample_json(name):
    """Return the JSON file ``name`` of the sample problem as data."""
    return json.loads((HACKATHON_2026 / name).read_text())


def sample_case(name="case.json"):
    """Return case ``name`` of the hackathon sample: environment, demand, constraints, prices."""
    return gm.Case.from_json(HACKATHON_2026 / name)


def shallow_case():
    """Return the case of the ``shallow_district`` sample."""
    return gm.Case.from_json(SHALLOW_DISTRICT / "case.json")


def treatment_plant():
    """Return the design with desander and inhibitor dosing, with the values of the sample case."""
    return apply_case(gm.Plant.from_dict(sample_json("plants/HackathonPlant.json")), sample_case())


def template_dict(name):
    """Return the plant dict of template plant ``name``, without the values of the case."""
    return sample_json(f"plants/{name}.json")


def template_plant(name):
    """Return template plant ``name`` with the values of the sample case set."""
    return apply_case(gm.Plant.from_dict(template_dict(name)), sample_case())


def filled_plant(name):
    """Return plant ``name`` with values: of the sample case for a template, else its example."""
    return template_plant(name) if name in (SAMPLE_PLANT, *TEMPLATES) else example_plant(name)


def example_plant(name):
    """Return plant ``name`` with the design values of ``inputs/plants/<name>.json``.

    The file gives ``size``, ``params`` and any ``fluids``, ``boundary``, ``bindings``,
    ``param_history`` and ``inputs`` under the keys of a plant dict. ``Doublet`` and
    ``DoubletHeatPlant`` carry the values of the measured doublet, the other plants the values
    their unit tests use. Only tests, scripts and examples read ``inputs/``.
    """
    values = from_json(paths.plant_values(name))
    plant = registry.get(name)(**values.get("size", {}))
    plant.set_params("", values["params"])
    from_sections(plant, values, Report(strict=True))
    reader.set_sections(plant, values)
    plant._stated[""] = {}
    return plant._set_si_inputs(values.get("inputs", {}))
