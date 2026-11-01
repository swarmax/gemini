"""Every analysis, economics, check, testing and optimisation name: JSON or not built."""

import copy
import json

import pytest

import gemini as gm
from gemini._utils.jsonable import to_plain
from tests.fixtures.booster_module import EXAMPLE, Booster
from tests.fixtures.cases import costed_finance, make_case
from tests.fixtures.costed_plants import day, heating_plant

CASE = {"wellhead_pressure": {"value": 4.6, "unit": "bar"}, "rates": [20, 45], "frequency": 55.484}
CORROSION = {
    "correlation": "NORSOK",
    "conditions": {
        "temperature": {"value": 60, "unit": "degC"},
        "pressure": {"value": 20, "unit": "bar"},
        "water_flow_rate": 0.01,
        "co2_partial_pressure": {"value": 2, "unit": "bar"},
        "diameter": 0.1,
    },
    "thickness": 0.008,
    "minimum_thickness": 0.005,
    "start": "2024-01-01T00:00:00Z",
}
PRICED = make_case(
    finance=costed_finance(
        opex={"electricity": gm.units.Quantity(2e-8, "currency/J")},
        revenue={"heat": gm.units.Quantity(5e-8, "currency/J")},
    ),
    emissions={"CO2": gm.case.CO2(electricity=gm.units.Quantity(1e-7, "kg/J"))},
)


@pytest.fixture(scope="module")
def example_run(shared_plant, fast_dataset):
    """Return a copy of the example plant and a six-hour replay of it."""
    plant = copy.deepcopy(shared_plant)
    return plant, gm.replay(plant, fast_dataset.window(None, "2024-07-01T06:00:00Z"))


def real_calls(example_run):
    """Return ``(name, result)`` of one call of every function that is built."""
    plant, replay = example_run
    costed, run = heating_plant(), day()
    problem, priced = make_case(), PRICED
    return [
        ("analysis.nodal", gm.analysis.nodal(plant, "doublet", CASE)),
        ("analysis.pump_curve", gm.analysis.pump_curve(plant, "doublet.esp")),
        ("analysis.corrosion_forecast", gm.analysis.corrosion_forecast(CORROSION, "2026-01-01")),
        ("kpi", gm.evaluate.totals(plant, problem, replay)),
        ("economics.capex", gm.evaluate.capex(costed, priced)),
        ("economics.opex", gm.evaluate.opex(costed, priced, run)),
        ("economics.lcoh", gm.evaluate.lcoh(costed, priced, run, 0.05, 20)),
        ("economics.lcoc", gm.evaluate.lcoc(costed, priced, run, 0.05, 20, on_error="record")),
        ("economics.co2", gm.evaluate.co2(costed, priced, run)),
        ("economics.npv", gm.evaluate.npv(costed, priced, run, 0.05, 20)),
        ("economics.payback", gm.evaluate.payback(costed, priced, run)),
        ("checks.energy_balance", gm.evaluate.energy_balance(plant, problem, replay)),
        ("checks.mass_balance", gm.evaluate.mass_balance(plant, problem, replay)),
        ("checks.bounds", gm.evaluate.bounds(plant, problem, replay)),
        ("checks.run_all", gm.evaluate.run_all(plant, problem, replay)),
        ("testing.check_module", gm.modules.check(Booster, EXAMPLE)),
    ]


def test_every_real_return_is_plain_json(example_run):
    """No NumPy type, no NaN and no infinity anywhere in a result."""
    for name, result in real_calls(example_run):
        plain = to_plain(result)
        text = json.dumps(plain, allow_nan=False)
        assert json.loads(text) == plain, name


@pytest.mark.parametrize(
    "call",
    [
        lambda: gm.analysis.injectivity(None, "doublet.injector"),
        lambda: gm.analysis.calibrate_pump(None, "doublet.esp", None),
        lambda: gm.analysis.calibrate_corrosion([]),
        lambda: gm.analysis.erosion(None, "doublet"),
    ],
    ids=["injectivity", "calibrate_pump", "calibrate_corrosion", "erosion"],
)
def test_every_name_not_built_raises_not_implemented_yet(call):
    """The final signature exists and the call says its work lands later."""
    with pytest.raises(gm.errors.NotImplementedYet):
        call()
