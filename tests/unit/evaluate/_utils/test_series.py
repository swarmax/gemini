"""Plant-level series read from the leaf columns of a run."""

import math

import pytest

import gemini as gm
from gemini.evaluate._utils import series
from gemini.modules import CoolingGrid, HeatingGrid
from tests.fixtures.result_tables import cold_ports, heat_ports, make_results


@pytest.fixture(scope="module")
def consumers():
    """Return a plant with one heat and two cooling consumers and a run over three hours."""
    plant = gm.Plant("Demo")
    plant.add("HeatingGrid", "heat")
    plant.add("CoolingGrid", "cool_a")
    plant.add("CoolingGrid", "cool_b")
    results = make_results(
        {
            "heat": heat_ports([1.0, 2.0, math.nan]),
            "cool_a": cold_ports([10.0, 20.0, math.nan]) | {"unmet_latent": [1.0, 2.0, math.nan]},
            "cool_b": cold_ports([1.0, math.nan, math.nan]) | {"unmet_latent": [1.0, 0.0, 0.0]},
            "pump": {"power_in": [5.0, 5.0, 5.0]},
        },
        step=1800.0,
    )
    return plant, results


def test_leaf_total_sums_the_leaves_of_one_class(consumers):
    """Outputs of cooling consumers add up, a heat consumer has none, a missing tick is NaN."""
    plant, results = consumers
    frame = results.to_frame()
    unmet = series.leaf_total(plant, frame, "unmet_latent", CoolingGrid)
    assert unmet.iloc[:2].tolist() == [2.0, 2.0]
    assert series.leaf_total(plant, frame, "unmet_latent", HeatingGrid) is None


def test_edge_totals_read_the_ports_of_the_edge_modules(consumers):
    """Delivered heat and cold are port differences; a missing tick is NaN."""
    plant, results = consumers
    frame = results.to_frame()
    assert series.port_difference(plant, frame, *series.HEAT_DELIVERED).iloc[:2].tolist() == [
        1.0,
        2.0,
    ]
    assert series.port_difference(plant, frame, *series.COLD_DELIVERED).iloc[0] == 11.0
    assert math.isnan(series.port_difference(plant, frame, *series.COLD_DELIVERED).iloc[1])


def test_leaf_total_is_none_without_a_declaring_leaf(consumers):
    """A field no leaf of the class declares gives no series."""
    plant, results = consumers
    assert series.leaf_total(plant, results.to_frame(), "unmet_demand", CoolingGrid) is None


def test_results_total_sums_by_field_name(consumers):
    """The power column is found without the plant."""
    _, results = consumers
    total = series.results_total(results, results.to_frame(), "power_in")
    assert total.tolist() == [5.0, 5.0, 5.0]
    assert series.results_total(results, results.to_frame(), "fuel") is None


def test_steps_are_the_energy_of_each_tick_and_skip_missing_ticks(consumers):
    """A missing tick gives no energy."""
    plant, results = consumers
    heat = series.port_difference(plant, results.to_frame(), *series.HEAT_DELIVERED)
    assert series.steps(heat, results.durations).tolist() == [1800.0, 3600.0, 0.0]


def test_energy_integrates_power_and_skips_missing_ticks(consumers):
    """Energy is power times duration, over the ticks that have a value."""
    plant, results = consumers
    heat = series.port_difference(plant, results.to_frame(), *series.HEAT_DELIVERED)
    assert series.energy(heat, results.durations) == (1.0 + 2.0) * 1800.0
