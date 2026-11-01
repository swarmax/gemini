"""Trials in worker processes give the numbers and the order of a serial run."""

import gemini as gm
from gemini.study._utils import parallel
from tests.unit.study.conftest import shallow_case, shallow_plant

PRICE = "case.assumptions.finance.opex.electricity"
DECLARED = {"assumptions.finance.opex.electricity": {"kind": "uniform", "min": 90, "max": 150}}


def settings_seen(shared, item):
    """Return the item, the shared value and the settings a worker runs with."""
    return item, shared, gm.runtime.get_processes(), gm.runtime.get_precision()


def test_the_results_come_back_in_the_order_of_the_items():
    """Items run in turn without processes and in workers with them, in the same order."""
    items = list(range(5))
    serial = parallel.mapped(settings_seen, "shared", items)
    assert [item for item, *_ in serial] == items and serial[0][2] == 1
    with gm.runtime.settings(processes=2, precision="float64"):
        workers = parallel.mapped(settings_seen, "shared", items)
    assert [(item, shared) for item, shared, *_ in workers] == [(i, "shared") for i in items]
    assert {(count, precision) for *_, count, precision in workers} == {(1, "float64")}


def test_one_item_runs_here_whatever_the_processes():
    """A single item needs no worker."""
    with gm.runtime.settings(processes=4):
        assert parallel.mapped(settings_seen, "x", [7]) == [(7, "x", 4, "float64")]


def test_a_sample_in_workers_equals_the_serial_sample(tmp_path):
    """The same draws give the same metrics, parameters and summary in processes as in turn."""
    case = shallow_case(days=1, folder=tmp_path, uncertain=DECLARED)
    plant = shallow_plant()
    serial = gm.study.sample(plant, case, ["peak_heat"], 2, 4)
    with gm.runtime.settings(processes=2):
        workers = gm.study.sample(plant, case, ["peak_heat"], 2, 4)
    assert workers.to_dict() == serial.to_dict()
