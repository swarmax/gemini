"""One trial of a search: the metrics it may read and the run it makes."""

import gemini as gm
from gemini.optim._utils import trial
from tests.fixtures.errors import raises
from tests.fixtures.result_tables import make_results


def test_a_metric_is_a_kpi_or_an_economic_figure():
    """The names a search may read; an unknown one is refused with the close names."""
    assert trial.checked_metric("peak_heat", None) == "peak_heat"
    assert trial.checked_metric("lcoh", object()) == "lcoh"
    with raises(gm.errors.ValidationError, "unknown_name", match="lcoh"):
        trial.checked_metric("lcox", None)


def test_an_economic_metric_needs_a_problem():
    """Its prices are in the problem."""
    with raises(gm.errors.ValidationError, "missing_value", match="assumptions"):
        trial.checked_metric("co2", None)


def test_a_search_needs_a_problem_or_a_plan():
    """Either is enough."""
    trial.require_input(object(), None)
    trial.require_input(None, object())
    with raises(gm.errors.ValidationError, "missing_value"):
        trial.require_input(None, None)


def test_a_trial_sets_the_values_on_a_copy_and_runs_it(monkeypatch):
    """The metrics of the run come back with no reason; the plant keeps its values."""
    seen = []

    def fake(plant, problem=None, plan=None):
        seen.append(plant)
        return make_results({"users": {"unmet_demand": [0.0]}})

    monkeypatch.setattr(trial, "simulate", fake)
    plant = gm.Plant("Boiler")
    plant.add(
        "Boiler", name="boiler", params={"capacity": {"value": 2, "unit": "MW"}, "efficiency": 0.9}
    )
    metrics, reason = trial.run_trial(plant, None, None, {"boiler.capacity": 1e6}, ["peak_heat"])
    assert reason is None and list(metrics) == ["peak_heat"]
    assert seen[0].params_at("boiler", None)["capacity"] == 1e6
    assert plant.params_at("boiler", None)["capacity"] == 2e6


def test_a_trial_that_fails_gives_its_reason(monkeypatch):
    """A failure of the run is a reason, not an error."""

    def fake(plant, problem=None, plan=None):
        raise gm.errors.ValidationError("no run", code="invalid_value")

    monkeypatch.setattr(trial, "simulate", fake)
    metrics, reason = trial.run_trial(gm.Plant("Empty"), None, None, {}, ["peak_heat"])
    assert metrics == {} and reason == "no run"
