"""Mass ledger of a run: synthetic columns and the example plant."""

import gemini as gm
from gemini._utils.jsonable import to_plain
from tests.fixtures.costed_plants import heating_plant
from tests.fixtures.result_tables import make_results

PLANT = heating_plant()


def test_mass_ledger_reads_the_columns_in_kg_per_second():
    """Only outputs whose unit is kg/s count; the other column is ignored."""
    columns = {"degasser": {"gas_mass_flow": [0.2, 0.0], "pressure_drop": [-5.0, -5.0]}}
    units = {"degasser": {"gas_mass_flow": "kg/s", "pressure_drop": "Pa"}}
    result = gm.evaluate.mass_balance(PLANT, None, make_results(columns, units=units))
    assert to_plain(result) == {
        "name": "mass_balance",
        "passed": True,
        "value": {"value": 0.0, "unit": "kg/s"},
        "limit": {"value": 1e-12, "unit": "kg/s"},
    }
    negative = make_results({"degasser": {"gas_mass_flow": [-0.1]}}, units=units)
    assert gm.evaluate.mass_balance(PLANT, None, negative)["passed"] is False


def test_mass_ledger_without_a_mass_flow_is_undecided():
    """No output in kg/s: nothing to judge."""
    result = gm.evaluate.mass_balance(PLANT, None, make_results({"leaf": {"head": [1.0]}}))
    assert result["passed"] is None
    assert result["value"].reason == "results have no output in kg/s"


def test_the_example_plant_run_passes_the_mass_ledger(fresh_plant, fast_dataset):
    """A six-hour replay of the doublet heat plant has non-negative mass flows."""
    replay = gm.replay(fresh_plant, fast_dataset.window(None, "2024-07-01T06:00:00Z"))
    assert gm.evaluate.mass_balance(fresh_plant, None, replay)["passed"] is True
