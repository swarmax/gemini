"""The heating and cooling plants run one simulate with stated assumptions."""

import pytest

import gemini as gm
from tests.fixtures.heating_cooling import HEAT, filled_dict, two_days

pytestmark = pytest.mark.slow

LIMITS = [
    gm.Constraint(
        "d*.reservoir.liquid_flow",
        min={"value": 50, "unit": "m3/h"},
        max={"value": 300, "unit": "m3/h"},
        when="running",
    ),
    gm.Constraint("d*.brine_cooling", max={"value": 40, "unit": "K"}),
]
ASSUMPTIONS = gm.Assumptions(
    prices={
        "electricity": {"value": 100, "unit": "EUR/MWh"},
        "gas": {"value": 40, "unit": "EUR/MWh"},
    }
)
PLANTS = (
    "HeatingPlant",
    "HeatingAbsorptionCoolingPlant",
    "HeatingHeatPumpCoolingPlant",
    "HeatingFullCoolingPlant",
)


def _problem():
    return gm.Problem(two_days(), constraints=LIMITS, assumptions=ASSUMPTIONS)


def _run(data):
    plant = gm.Plant.from_dict(data)
    return plant, gm.simulate(plant, _problem(), on_error="raise")


@pytest.mark.parametrize("name", PLANTS)
def test_every_plant_runs_one_simulate(name):
    """A plant builds, validates and runs two ticks without a row error."""
    data = filled_dict(name)
    assert gm.plants.validate(data) == []
    plant, results = _run(data)
    assert results.errors() == []
    frame = results.to_frame()
    delivered = frame["heating_consumer.supply_in.enthalpy_flow"]
    delivered = delivered - frame["heating_consumer.return_out.enthalpy_flow"]
    assert delivered.min() == pytest.approx(HEAT)


def _without(data, modules, joined):
    """Return ``data`` without ``modules``; ``joined`` are the ends to connect around them."""
    kept = {name: entry for name, entry in data["modules"].items() if name not in modules}
    connections = [
        item
        for item in data["connections"]
        if item["source"].partition(".")[0] not in modules
        and item["target"].partition(".")[0] not in modules
    ]
    links = [{"source": source, "target": target} for source, target in joined]
    inputs = {
        path: value
        for path, value in data["inputs"].items()
        if path.partition(".")[0] not in modules
    }
    return data | {"modules": kept, "connections": connections + links, "inputs": inputs}


def _sources(data, target):
    return next(item["source"] for item in data["connections"] if item["target"] == target)


def _targets(data, source):
    return next(item["target"] for item in data["connections"] if item["source"] == source)


def test_an_agent_removes_a_unit_by_editing_the_plant_dict():
    """The peak boiler leaves with its gas chain and what it joined is connected around it."""
    data = filled_dict("HeatingCoolingPlant")
    joined = [
        (_sources(data, "peak_boiler.fluid_in"), _targets(data, "peak_boiler.fluid_out")),
        (_sources(data, "gas_makeup.gas_in"), _targets(data, "gas_makeup.excess_out")),
    ]
    edited = _without(data, ("peak_boiler", "gas_grid", "gas_makeup"), joined)
    plant, results = _run(edited)
    assert results.errors() == []
    assert "peak_boiler" not in results.names()
    assert max(results.get("heating_consumer", "unmet_demand")["value"]) < 1e-6
