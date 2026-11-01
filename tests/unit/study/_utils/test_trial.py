"""One trial of a search: the metrics it may read and the run it makes."""

import gemini as gm
from gemini.study._utils import trial
from tests.fixtures.errors import raises
from tests.fixtures.result_tables import make_results
from tests.unit.study.conftest import shallow_case, shallow_plant

PRICE = "case.assumptions.finance.opex.electricity"


def test_a_metric_is_a_kpi_or_an_economic_figure():
    """The names a search may read; an unknown one is refused with the close names."""
    assert trial.checked_metric("peak_heat") == "peak_heat"
    assert trial.checked_metric("lcoh") == "lcoh"
    with raises(gm.errors.ValidationError, "unknown_name", match="lcoh"):
        trial.checked_metric("lcox")


def test_a_trial_sets_the_values_on_copies_and_runs_them(monkeypatch):
    """A parameter goes to the plant and a number of the case to the case; the originals stay."""
    seen = []

    def fake(plant, case=None, plan=None):
        seen.append((plant, case))
        return make_results({"users": {"unmet_demand": [0.0]}})

    monkeypatch.setattr(trial, "simulate", fake)
    monkeypatch.setattr(trial, "metric", lambda plant, case, results, name: name)
    plant, case = shallow_plant(), shallow_case()
    values = {"peak_boiler.capacity": 1e6, PRICE: 2e-8}
    metrics, reason = trial.run_trial(plant, case, None, values, ["peak_heat"])
    assert reason is None and metrics == {"peak_heat": "peak_heat"}
    assert seen[0][0].get_submodule("peak_boiler").capacity == 1e6
    assert seen[0][1].assumptions.finance.opex.electricity == 2e-8
    assert plant.get_submodule("peak_boiler").capacity == 3.5e6
    assert case.assumptions.finance.opex.electricity != 2e-8


def test_a_trial_that_fails_gives_its_reason(monkeypatch):
    """A failure of the run is a reason, not an error."""

    def fake(plant, case=None, plan=None):
        raise gm.errors.ValidationError("no run", code="invalid_value")

    monkeypatch.setattr(trial, "simulate", fake)
    metrics, reason = trial.run_trial(shallow_plant(), shallow_case(), None, {}, ["peak_heat"])
    assert metrics == {} and reason == "no run"
