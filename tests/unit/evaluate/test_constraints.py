"""Constraints on result fields and on parameters, against hand-made runs."""

import math

import pytest

import gemini as gm
from gemini._utils.jsonable import to_plain
from gemini.modules import HeatingGrid
from tests.fixtures.costed_plants import heating_plant
from tests.fixtures.errors import raises
from tests.fixtures.result_tables import make_problem, make_results

HOUR = 3600.0
UNMET = [1.0, 5.0, 3.0, 0.0]
RUNNING = [1.0, 1.0, 0.0, 1.0]


def run(unmet=UNMET, operating=RUNNING):
    """Return a run of the heat consumer: its unmet demand [W] and whether it carried flow."""
    return make_results({"heat": {"unmet_demand": unmet, "operating": operating}})


def checked(*constraints, plant=None, results=None, site=None):
    """Return the checks of ``constraints`` on a run."""
    problem = make_problem(count=4, constraints=list(constraints), site=site)
    return gm.evaluate.constraints(plant or heating_plant(), problem, results or run())


def only(*constraints, **parts):
    """Return the one check of ``constraints``."""
    (result,) = checked(*constraints, **parts)
    return result


def test_each_reports_the_worst_step_of_a_violated_maximum():
    """The second hour is the highest: its value, the limit and its time."""
    result = only(gm.Constraint("heat.unmet_demand", max=gm.units.Quantity(4.0, "W")))
    assert to_plain(result) == {
        "name": "heat.unmet_demand",
        "path": "heat.unmet_demand",
        "passed": False,
        "value": {"value": 5.0, "unit": "W"},
        "limit": {"value": 4.0, "unit": "W"},
        "worst_step": "2024-01-01T01:00:00+00:00",
    }


def test_each_passes_with_the_value_nearest_the_limit():
    """The highest value is still under the maximum."""
    result = only(gm.Constraint("heat.unmet_demand", max=gm.units.Quantity(6.0, "W")))
    assert result["passed"] is True and result["value"].value == 5.0
    assert result["limit"].value == 6.0


def test_each_with_two_bounds_reports_the_one_that_is_further_out():
    """Zero is 2 under the minimum, 5 is 1 over the maximum: the low end is further out."""
    result = only(
        gm.Constraint(
            "heat.unmet_demand", min=gm.units.Quantity(2.0, "W"), max=gm.units.Quantity(4.0, "W")
        ),
        results=run(operating=[1] * 4),
    )
    assert result["passed"] is False
    assert result["value"].value == 0.0 and result["limit"].value == 2.0
    assert result["worst_step"] == "2024-01-01T03:00:00+00:00"


def test_equals_is_both_bounds():
    """A constant run equals its value; another value does not."""
    flat = run(unmet=[2.0] * 4, operating=[1] * 4)
    assert (
        only(gm.Constraint("heat.unmet_demand", equals=gm.units.Quantity(2.0, "W")), results=flat)[
            "passed"
        ]
        is True
    )
    assert (
        only(gm.Constraint("heat.unmet_demand", equals=gm.units.Quantity(3.0, "W")), results=flat)[
            "passed"
        ]
        is False
    )


def test_a_value_on_the_limit_passes_within_the_rounding_margin():
    """A relative 1e-9 of rounding does not fail a limit."""
    result = only(gm.Constraint("heat.unmet_demand", max=gm.units.Quantity(5.0 * (1 - 1e-12), "W")))
    assert result["passed"] is True


@pytest.mark.parametrize(
    "over, figure",
    [("sum", 9.0), ("mean", 2.25), ("max", 5.0), ("min", 0.0)],
)
def test_an_aggregate_judges_one_figure_of_the_run(over, figure):
    """The figure is the value, the bound is the limit and no step is the worst."""
    flat = run(operating=[1] * 4)
    result = only(
        gm.Constraint(
            "heat.unmet_demand",
            min=gm.units.Quantity(figure - 1, "W"),
            max=gm.units.Quantity(figure + 1, "W"),
            over=over,
        ),
        results=flat,
    )
    assert result["passed"] is True
    assert to_plain(result["value"]) == {"value": figure, "unit": "W"}
    assert result["worst_step"] is None
    broken = only(
        gm.Constraint("heat.unmet_demand", max=gm.units.Quantity(figure - 1, "W"), over=over),
        results=flat,
    )
    assert broken["passed"] is False and broken["limit"].value == figure - 1


def test_running_leaves_out_the_steps_without_flow():
    """The 3 W of the idle hour does not count while the module is running."""
    idle = run(unmet=[4.0, 4.0, 0.5, 4.0])
    assert (
        only(gm.Constraint("heat.unmet_demand", min=gm.units.Quantity(1.0, "W")), results=idle)[
            "passed"
        ]
        is False
    )
    running = only(
        gm.Constraint("heat.unmet_demand", min=gm.units.Quantity(1.0, "W"), when="running"),
        results=idle,
    )
    assert running["passed"] is True and running["value"].value == 4.0


def test_a_module_that_never_ran_is_undecided():
    """No step counts: ``passed`` is None and the value says why."""
    stopped = run(operating=[0] * 4)
    result = only(
        gm.Constraint("heat.unmet_demand", max=gm.units.Quantity(1.0, "W"), when="running"),
        results=stopped,
    )
    assert result["passed"] is None
    assert to_plain(result["value"]) == {
        "value": None,
        "unit": "W",
        "reason": "the module carried no flow in this run",
    }
    assert to_plain(result["limit"]) == {"value": 1.0, "unit": "W"}


def test_duration_is_the_time_of_the_steps_that_count():
    """Three of four hours the module ran: 10800 s, within half a step of 3.4 hours."""
    constraint = gm.Constraint
    ran = only(
        constraint(
            "heat.unmet_demand", equals={"value": 3, "unit": "h"}, over="duration", when="running"
        )
    )
    assert to_plain(ran["value"]) == {"value": 3 * HOUR, "unit": "s"}
    assert ran["passed"] is True and ran["worst_step"] is None
    near = constraint(
        "heat.unmet_demand", equals={"value": 3.4, "unit": "h"}, over="duration", when="running"
    )
    assert only(near)["passed"] is True
    far = constraint(
        "heat.unmet_demand", equals={"value": 4, "unit": "h"}, over="duration", when="running"
    )
    assert only(far)["passed"] is False
    assert to_plain(only(far)["limit"]) == {"value": 4 * HOUR, "unit": "s"}


def test_duration_without_a_condition_counts_every_step_with_a_value():
    """Four hours, less the one that failed."""
    gap = run(unmet=[1.0, math.nan, 3.0, 0.0])
    assert only(
        gm.Constraint("heat.unmet_demand", min=gm.units.Quantity(3 * HOUR, "s"), over="duration"),
        results=gap,
    )["passed"]
    assert (
        only(
            gm.Constraint(
                "heat.unmet_demand", min=gm.units.Quantity(4 * HOUR, "s"), over="duration"
            ),
            results=gap,
        )["passed"]
        is False
    )


def test_duration_bounds_are_durations():
    """A maximum and a minimum in seconds and in text give the same answer."""
    a = only(
        gm.Constraint(
            "heat.unmet_demand",
            max=gm.units.Quantity(10800.0, "s"),
            over="duration",
            when="running",
        )
    )
    b = only(
        gm.Constraint(
            "heat.unmet_demand", max={"value": 3, "unit": "h"}, over="duration", when="running"
        )
    )
    assert a == b | {"limit": a["limit"]} and a["passed"] is True


def test_bounds_are_converted_to_the_unit_of_the_field():
    """2 kW is 2000 W."""
    result = only(gm.Constraint("heat.unmet_demand", max={"value": 2, "unit": "kW"}))
    assert result["passed"] is True and result["limit"].value == 2000.0


def test_a_field_the_run_lacks_is_undecided():
    """The field exists on the module but the results hold no column of it."""
    result = only(gm.Constraint("heat.surplus", max=gm.units.Quantity(1.0, "W")), results=run())
    assert result["passed"] is None
    assert result["value"].reason.startswith("no_value")


def test_a_failed_run_with_only_missing_values_is_undecided():
    """Every row failed: no value."""
    result = only(
        gm.Constraint("heat.unmet_demand", max=gm.units.Quantity(1.0, "W")),
        results=run(unmet=[math.nan] * 4),
    )
    assert result["passed"] is None and result["value"].reason.startswith("no_value")


def test_a_port_quantity_is_a_field():
    """A temperature of a port, in a unit of the user."""
    results = make_results(
        {"heat": {"return_out.temperature": [300.0, 320.0], "operating": [1.0, 1.0]}}
    )
    problem = make_problem(
        count=2,
        constraints=[
            gm.Constraint("heat.return_out.temperature", max={"value": 40, "unit": "degC"})
        ],
    )
    result = gm.evaluate.constraints(heating_plant(), problem, results)[0]
    assert result["passed"] is False and result["value"].value == 320.0
    assert result["limit"].value == pytest.approx(313.15)


def test_a_pattern_checks_each_match_on_its_own():
    """Two consumers, two answers; ``*`` stays within a name."""
    plant = heating_plant()
    plant._add_module("heat2", HeatingGrid())
    results = make_results(
        {
            "heat": {"unmet_demand": [1.0], "operating": [1.0]},
            "heat2": {"unmet_demand": [9.0], "operating": [1.0]},
        }
    )
    problem = make_problem(
        count=1, constraints=[gm.Constraint("heat*.unmet_demand", max=gm.units.Quantity(5.0, "W"))]
    )
    found = gm.evaluate.constraints(plant, problem, results)
    assert [(item["name"], item["passed"]) for item in found] == [
        ("heat.unmet_demand", True),
        ("heat2.unmet_demand", False),
    ]
    assert {item["path"] for item in found} == {"heat*.unmet_demand"}


def test_a_pattern_without_a_module_or_a_field_is_refused():
    """The names that exist are suggested."""
    with raises(gm.errors.ValidationError, "unknown_name", match="matches no module"):
        checked(gm.Constraint("hat.unmet_demand", max=gm.units.Quantity(1.0, "W")))
    with raises(gm.errors.ValidationError, "unknown_name", match="no field"):
        checked(gm.Constraint("heat.unmet_deman", max=gm.units.Quantity(1.0, "W")))


def test_a_parameter_is_judged_with_the_site_of_the_problem():
    """The plant states no return temperature; the site gives 30 degC, over the 25 degC maximum."""
    plant = heating_plant()
    constraint = gm.Constraint("heat.return_temperature", max={"value": 25, "unit": "degC"})
    result = only(
        constraint, plant=plant, site={"heat.return_temperature": {"value": 30, "unit": "degC"}}
    )
    assert result["passed"] is False
    assert result["value"].value == pytest.approx(303.15)
    assert result["worst_step"] is None
    assert result["limit"].value == pytest.approx(298.15)


def test_a_parameter_the_plant_states_is_judged_as_it_is():
    """No site: the stated value is the figure."""
    plant = heating_plant()
    plant.set_params("heat", {"return_temperature": 303.15})
    result = only(
        gm.Constraint("heat.return_temperature", min={"value": 20, "unit": "degC"}), plant=plant
    )
    assert result["passed"] is True and result["value"].unit == "K"


def test_a_parameter_without_a_value_is_undecided():
    """Nothing states it."""
    result = only(gm.Constraint("heat.return_temperature", max=gm.units.Quantity(300.0, "K")))
    assert result["passed"] is None and result["value"].reason.startswith("no_value")


@pytest.mark.parametrize("over", ["sum", "mean", "max", "min", "duration"])
def test_a_parameter_takes_only_each(over):
    """A parameter has no steps to aggregate."""
    bound = gm.units.Quantity(300.0, "s" if over == "duration" else "K")
    with raises(gm.errors.ValidationError, "invalid_value", match="parameter"):
        checked(gm.Constraint("heat.return_temperature", max=bound, over=over))


def test_every_constraint_of_the_problem_is_checked_in_order():
    """Two constraints, two checks."""
    found = checked(
        gm.Constraint("heat.unmet_demand", max=gm.units.Quantity(9.0, "W")),
        gm.Constraint("heat.unmet_demand", min=gm.units.Quantity(0.0, "W")),
    )
    assert [item["passed"] for item in found] == [True, True]


def test_a_problem_without_constraints_gives_no_checks():
    """Nothing to check."""
    assert checked() == []


def test_an_output_of_a_plant_is_read_through_the_leaves_it_names():
    """The brine cooling of a doublet is the riser's outlet less the injector's inlet."""
    plant = gm.Plant("One")
    plant.add("Doublet", name="d0")
    results = make_results(
        {
            "d0.riser": {"wellhead_out.temperature": [380.0, 390.0], "operating": [1.0, 1.0]},
            "d0.injector": {"wellhead_in.temperature": [340.0, 340.0], "operating": [1.0, 0.0]},
        }
    )
    limit = gm.Constraint("d0.brine_cooling", max={"value": 45, "unit": "K"})
    problem = make_problem(count=2, constraints=[limit])
    assert gm.evaluate.constraints(plant, problem, results)[0]["value"].value == 50.0
    running = gm.Constraint("d0.brine_cooling", max={"value": 45, "unit": "K"}, when="running")
    problem = make_problem(count=2, constraints=[running])
    found = gm.evaluate.constraints(plant, problem, results)[0]
    assert found["passed"] is True and found["value"].value == 40.0
