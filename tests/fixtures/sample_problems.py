"""The sample cases of ``inputs/examples/``: only examples and tests read them."""

import json

import gemini as gm
from gemini._utils import paths
from gemini.run._utils.apply import apply_case

HACKATHON_2027 = paths.INPUTS / "examples/hackathon_2027"
SHALLOW_DISTRICT = paths.INPUTS / "examples/shallow_district"
SAMPLE_PLANT = "HeatingCoolingPlant"
"""The class of the design in ``plant.json``; the other template plants are in ``templates/``."""
TEMPLATES = (
    "HeatingPlant",
    "HeatingAbsorptionCoolingPlant",
    "HeatingHeatPumpCoolingPlant",
    "HeatingFullCoolingPlant",
)


def sample_json(name):
    """Return the JSON file ``name`` of the sample problem as data."""
    return json.loads((HACKATHON_2027 / name).read_text())


def sample_case(name="case.json"):
    """Return case ``name`` of the hackathon sample: environment, demand, constraints, prices."""
    return gm.Case.from_json(HACKATHON_2027 / name)


def shallow_case():
    """Return the case of the ``shallow_district`` sample."""
    return gm.Case.from_json(SHALLOW_DISTRICT / "case.json")


def treatment_plant():
    """Return the design with desander and inhibitor dosing, with the values of the sample case."""
    return apply_case(gm.Plant.from_dict(sample_json("plant_with_treatment.json")), sample_case())


def template_dict(name):
    """Return the plant dict of template plant ``name``, without the values of the case."""
    return sample_json("plant.json" if name == SAMPLE_PLANT else f"templates/{name}.json")


def template_plant(name):
    """Return template plant ``name`` with the values of the sample case set."""
    return apply_case(gm.Plant.from_dict(template_dict(name)), sample_case())


def filled_plant(name):
    """Return plant ``name`` with values: of the sample case for a template, else its example."""
    return template_plant(name) if name in (SAMPLE_PLANT, *TEMPLATES) else gm.plants.example(name)
