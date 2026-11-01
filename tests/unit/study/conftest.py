"""A shallow plant and case, and a run replaced by a cost model, shared by the study tests."""

import pandas as pd
import pytest

import gemini as gm
from gemini._utils.files import from_json
from gemini.case._utils.kinds import EQUIPMENT_KINDS
from gemini.plants._utils.roles import units_of
from gemini.study._utils import trial
from gemini.types.shapes import measure
from tests.fixtures.result_tables import make_results
from tests.fixtures.sample_cases import SHALLOW_DISTRICT

SAMPLE = SHALLOW_DISTRICT
COUNT_COST = {1: 5.0, 2: 3.0, 3: 4.0}
"""The cost of a plant of 1, 2 and 3 doublets before the depth and the price are added."""


PLACEHOLDERS = {
    "money_per_length": {"value": 500, "unit": "EUR/m"},
    "money_per_power": {"value": 0.5, "unit": "EUR/W"},
    "money_per_conductance": {"value": 0.05, "unit": "EUR/(W/K)"},
    "money_per_volume": {"value": 500, "unit": "EUR/m3"},
    "money": {"value": 1e5, "unit": "EUR"},
}
"""A cost factor of each basis for a kind the sample case gives none: the test needs a number."""


def shallow_case(days=None, folder=None, uncertain=None, **sections):
    """Return the shallow sample case with the choices of the study tests, plus ``sections``.

    ``uncertain`` maps the dotted path of a number of the case to its ``uncertainty`` dict, as
    ``case.json`` writes it next to the value. ``days`` keeps only the first days of the sample
    demand, written to ``folder``, so that a real run is short.
    """
    data = from_json(SAMPLE / "case.json")
    where = SAMPLE
    if days is not None:
        frame = pd.read_csv(SAMPLE / data["demand"]["file"]).iloc[: 24 * days]
        frame.to_csv(folder / data["demand"]["file"], index=False)
        data["time"]["end"] = str(pd.Timestamp(data["time"]["start"]) + pd.Timedelta(days=days))[
            :10
        ]
        where = folder
        for item in data["constraints"]:
            if item.get("over") == "duration":
                item["max"]["value"] = 20 * days
    data["choices"] = {
        "doublets": {"min": 1, "max": 3},
        "depth": {"min": {"value": 1000, "unit": "m"}, "max": {"value": 2000, "unit": "m"}},
    }
    capex = data["assumptions"]["finance"]["capex"]
    for kind, (basis, _) in EQUIPMENT_KINDS.items():
        capex.setdefault(kind, PLACEHOLDERS[basis])
    fixed = data["assumptions"]["finance"]["opex"].setdefault("fixed", {})
    for kind in EQUIPMENT_KINDS:
        fixed.setdefault(kind, {"value": 2, "unit": "%/yr"})
    for path, uncertainty in (uncertain or {}).items():
        *parents, last = path.split(".")
        node = data
        for part in parents:
            node = node[part]
        value = node[last]
        node[last] = {**value, "uncertainty": uncertainty} if isinstance(value, dict) else {
            "value": value,
            "uncertainty": uncertainty,
        }
    return gm.Case.from_dict(data | sections, where)


def shallow_plant():
    """Return the shallow sample plant, on one doublet."""
    return gm.Plant.from_json(SAMPLE / "plant.json")


def cost_model(plant, case, results, name):
    """Return a metric of a plant by a cost that is known by hand.

    ``lcts`` is the count cost, plus the square of the distance of the depth to 1500 m in km, plus
    the electricity price in EUR/MWh over 1000; ``peak_heat`` is the capacity of the peak boiler.
    """
    count = len(units_of(plant, "doublet"))
    price = case.assumptions.finance.opex.electricity * 3.6e9
    if name == "lcts":
        cost = COUNT_COST[count] + ((plant.depth - 1500) / 1000) ** 2 + price / 1000
        return measure(cost, "currency/J")
    if name == "co2":
        return measure(plant.depth / 1000, "kg")
    return measure(plant.get_submodule("peak_boiler").capacity, "W")


@pytest.fixture
def runs(monkeypatch):
    """Replace the simulation of a trial by an empty result and its metrics by ``cost_model``.

    The fixture value lists the ``(plant, case, plan)`` of every simulation.
    """
    calls = []

    def fake(plant, case=None, plan=None):
        calls.append((plant, case, plan))
        return make_results({"users": {"unmet_demand": [0.0]}})

    monkeypatch.setattr(trial, "simulate", fake)
    monkeypatch.setattr(trial, "metric", cost_model)
    monkeypatch.setattr(trial, "constraints", lambda plant, case, results: [])
    return calls
