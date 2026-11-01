"""All checks together."""

import gemini as gm
from tests.fixtures.cases import make_case
from tests.fixtures.costed_plants import heating_plant
from tests.fixtures.result_tables import make_results


def test_run_all_lists_the_three_checks():
    """The ledgers and the bounds, in order, and a passing verdict."""
    results = make_results(
        {"grid": {"power_out": [1.0]}, "heat": {"return_out.temperature": [300.0]}}
    )
    report = gm.evaluate.run_all(heating_plant(), make_case(), results)
    assert [item["name"] for item in report["checks"]] == [
        "energy_balance",
        "mass_balance",
        "bounds",
    ]
    assert [item["passed"] for item in report["checks"]] == [True, None, True]
    assert report["passed"] is True


def test_the_constraints_of_the_case_join_the_checks():
    """Each match of a constraint is one more check and can fail the run."""
    results = make_results(
        {"heat": {"unmet_demand": [7.0], "return_out.temperature": [300.0], "operating": [1.0]}}
    )
    limit = gm.case.Constraint(
        on="heating_supply", quantity="unmet", max=gm.units.Quantity(5.0, "W")
    )
    report = gm.evaluate.run_all(heating_plant(), make_case(count=1, constraints=[limit]), results)
    assert report["checks"][-1]["name"] == "heat.unmet_demand"
    assert report["checks"][-1]["passed"] is False and report["passed"] is False


def test_one_failure_fails_the_run():
    """A negative fuel power fails the energy ledger and the whole report."""
    results = make_results({"heat": {"fuel": [-1.0], "return_out.temperature": [300.0]}})
    assert gm.evaluate.run_all(heating_plant(), make_case(), results)["passed"] is False
