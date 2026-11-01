"""Constraints on roles and on the supply temperatures, against hand-made runs."""

import math

import pytest

import gemini as gm
from gemini._utils.jsonable import to_plain
from gemini.modules import HeatingGrid
from gemini.units import Quantity
from tests.fixtures.cases import make_case
from tests.fixtures.costed_plants import heating_plant
from tests.fixtures.errors import raises
from tests.fixtures.result_tables import make_results

HOUR = 3600.0
UNMET = [1.0, 5.0, 3.0, 0.0]
RUNNING = [1.0, 1.0, 0.0, 1.0]


def run(unmet=UNMET, operating=RUNNING):
    """Return a run of the heat consumer: its unmet demand [W] and whether it carried flow."""
    return make_results({"heat": {"unmet_demand": unmet, "operating": operating}})


def unmet(**kwargs):
    """Return a constraint on the unmet demand of every heating supply."""
    return gm.case.Constraint(on="heating_supply", quantity="unmet", **kwargs)


def watts(value):
    """Return ``value`` watts."""
    return Quantity(value, "W")


def checked(*constraints, plant=None, results=None, supply=None):
    """Return the checks of ``constraints`` on a run."""
    case = make_case(count=4, constraints=list(constraints) or None, supply=supply)
    return gm.evaluate.constraints(plant or heating_plant(), case, results or run())


def only(*constraints, **parts):
    """Return the one check of ``constraints``."""
    (result,) = checked(*constraints, **parts)
    return result


def test_each_reports_the_worst_step_of_a_violated_maximum():
    """The second hour is the highest: its value, the limit and its time."""
    result = only(unmet(max=watts(4.0)))
    assert to_plain(result) == {
        "name": "heat.unmet_demand",
        "role": "heating_supply",
        "unit_path": "heat",
        "quantity": "unmet",
        "passed": False,
        "value": {"value": 5.0, "unit": "W"},
        "limit": {"value": 4.0, "unit": "W"},
        "worst_step": "2024-01-01T01:00:00+00:00",
    }


def test_each_passes_with_the_value_nearest_the_limit():
    """The highest value is still under the maximum."""
    result = only(unmet(max=watts(6.0)))
    assert result["passed"] is True and result["value"].value == 5.0
    assert result["limit"].value == 6.0


def test_each_with_two_bounds_reports_the_one_that_is_further_out():
    """Zero is 2 under the minimum, 5 is 1 over the maximum: the low end is further out."""
    result = only(unmet(min=watts(2.0), max=watts(4.0)), results=run(operating=[1] * 4))
    assert result["passed"] is False
    assert result["value"].value == 0.0 and result["limit"].value == 2.0
    assert result["worst_step"] == "2024-01-01T03:00:00+00:00"


def test_equals_is_both_bounds():
    """A constant run equals its value; another value does not."""
    flat = run(unmet=[2.0] * 4, operating=[1] * 4)
    assert only(unmet(equals=watts(2.0)), results=flat)["passed"] is True
    assert only(unmet(equals=watts(3.0)), results=flat)["passed"] is False


def test_a_value_on_the_limit_passes_within_the_rounding_margin():
    """A relative 1e-9 of rounding does not fail a limit."""
    assert only(unmet(max=watts(5.0 * (1 - 1e-12))))["passed"] is True


@pytest.mark.parametrize(
    "over, figure",
    [("sum", 9.0), ("mean", 2.25), ("max", 5.0), ("min", 0.0)],
)
def test_an_aggregate_judges_one_figure_of_the_run(over, figure):
    """The figure is the value, the bound is the limit and no step is the worst."""
    flat = run(operating=[1] * 4)
    result = only(unmet(min=watts(figure - 1), max=watts(figure + 1), over=over), results=flat)
    assert result["passed"] is True
    assert to_plain(result["value"]) == {"value": figure, "unit": "W"}
    assert result["worst_step"] is None
    broken = only(unmet(max=watts(figure - 1), over=over), results=flat)
    assert broken["passed"] is False and broken["limit"].value == figure - 1


def test_running_leaves_out_the_steps_without_flow():
    """The 3 W of the idle hour does not count while the module is running."""
    idle = run(unmet=[4.0, 4.0, 0.5, 4.0])
    assert only(unmet(min=watts(1.0)), results=idle)["passed"] is False
    running = only(unmet(min=watts(1.0), when="running"), results=idle)
    assert running["passed"] is True and running["value"].value == 4.0


def test_a_module_that_never_ran_is_undecided():
    """No step counts: ``passed`` is None and the value says why."""
    result = only(unmet(max=watts(1.0), when="running"), results=run(operating=[0] * 4))
    assert result["passed"] is None
    assert to_plain(result["value"]) == {
        "value": None,
        "unit": "W",
        "reason": "the module carried no flow in this run",
    }
    assert to_plain(result["limit"]) == {"value": 1.0, "unit": "W"}


def test_duration_is_the_time_of_the_steps_that_count():
    """Three of four hours the module ran: 10800 s, within half a step of 3.4 hours."""

    def hours(count):
        return Quantity(count, "h")

    ran = only(unmet(equals=hours(3), over="duration", when="running"))
    assert to_plain(ran["value"]) == {"value": 3 * HOUR, "unit": "s"}
    assert ran["passed"] is True and ran["worst_step"] is None
    assert only(unmet(equals=hours(3.4), over="duration", when="running"))["passed"] is True
    far = only(unmet(equals=hours(4), over="duration", when="running"))
    assert far["passed"] is False
    assert to_plain(far["limit"]) == {"value": 4 * HOUR, "unit": "s"}


def test_duration_without_a_condition_counts_every_step_with_a_value():
    """Four hours, less the one that failed."""
    gap = run(unmet=[1.0, math.nan, 3.0, 0.0])
    assert only(unmet(min=Quantity(3 * HOUR, "s"), over="duration"), results=gap)["passed"]
    far = only(unmet(min=Quantity(4 * HOUR, "s"), over="duration"), results=gap)
    assert far["passed"] is False


def test_bounds_of_another_unit_are_stored_in_the_unit_of_the_field():
    """2 kW is 2000 W."""
    result = only(unmet(max=Quantity(2, "kW")))
    assert result["passed"] is True and result["limit"].value == 2000.0


def test_a_field_the_run_lacks_is_undecided():
    """The field exists on the module but the results hold no column of it."""
    results = make_results({"heat": {"surplus": [1.0] * 4, "operating": [1.0] * 4}})
    result = only(unmet(max=watts(1.0)), results=results)
    assert result["passed"] is None
    assert result["value"].reason.startswith("no_value")


def test_a_failed_run_with_only_missing_values_is_undecided():
    """Every row failed: no value."""
    result = only(unmet(max=watts(1.0)), results=run(unmet=[math.nan] * 4))
    assert result["passed"] is None and result["value"].reason.startswith("no_value")


def test_a_port_quantity_is_a_field():
    """The temperature of the supply port of a consumer, in kelvin."""
    results = make_results(
        {"heat": {"supply_in.temperature": [300.0, 320.0], "operating": [1.0, 1.0]}}
    )
    constraint = gm.case.Constraint(
        on="heating_supply", quantity="temperature", max=Quantity(40, "degC")
    )
    case = make_case(count=2, constraints=[constraint])
    result = gm.evaluate.constraints(heating_plant(), case, results)[0]
    assert result["name"] == "heat.supply_in.temperature"
    assert result["passed"] is False and result["value"].value == 320.0
    assert result["limit"].value == pytest.approx(313.15)


def test_a_role_checks_each_of_its_units_on_its_own():
    """Two consumers, two answers."""
    plant = heating_plant()
    plant._add_module("heat2", HeatingGrid())
    results = make_results(
        {
            "heat": {"unmet_demand": [1.0], "operating": [1.0]},
            "heat2": {"unmet_demand": [9.0], "operating": [1.0]},
        }
    )
    case = make_case(count=1, constraints=[unmet(max=watts(5.0))])
    found = gm.evaluate.constraints(plant, case, results)
    assert [(item["unit_path"], item["passed"]) for item in found] == [
        ("heat", True),
        ("heat2", False),
    ]
    assert {item["role"] for item in found} == {"heating_supply"}


def test_a_role_without_a_unit_in_the_plant_is_one_undecided_check():
    """A plant with no doublet has nothing to judge by a doublet limit: no value, no error."""
    flow = gm.case.Constraint(on="doublet", quantity="production_flow", max=Quantity(300, "m3/h"))
    (found,) = checked(flow)
    assert found["passed"] is None and found["unit_path"] is None
    assert found["role"] == "doublet" and found["name"] == "doublet.production_flow"
    assert found["value"].value is None and found["value"].reason.startswith("no_value")
    assert found["limit"].value == pytest.approx(300 / 3600) and found["limit"].unit == "m3/s"


def test_a_parameter_is_judged_as_the_plant_states_it():
    """The pump efficiency of a doublet, equal to 0.7."""
    plant = gm.Plant("One")
    plant.add("Doublet", name="d0", params={"pump_efficiency": 0.6})
    constraint = gm.case.Constraint(on="doublet", quantity="pump_efficiency", equals=0.7)
    result = only(constraint, plant=plant, results=make_results({"d0.esp": {"head": [1.0]}}))
    assert result["passed"] is False and result["worst_step"] is None
    assert result["value"].value == 0.6 and result["limit"].value == 0.7
    assert result["unit_path"] == "d0" and result["name"] == "d0.pump_efficiency"


def test_a_parameter_without_a_value_is_undecided():
    """Nothing states it."""
    plant = gm.Plant("One")
    plant.add("Doublet", name="d0")
    constraint = gm.case.Constraint(on="doublet", quantity="pump_efficiency", equals=0.7)
    result = only(constraint, plant=plant, results=make_results({"d0.esp": {"head": [1.0]}}))
    assert result["passed"] is None and result["value"].reason.startswith("no_value")


@pytest.mark.parametrize("over", ["sum", "mean", "max", "min", "duration"])
def test_a_parameter_takes_only_each(over):
    """A parameter has no steps to aggregate."""
    plant = gm.Plant("One")
    plant.add("Doublet", name="d0", params={"pump_efficiency": 0.6})
    bound = Quantity(300.0, "s") if over == "duration" else 0.7
    constraint = gm.case.Constraint(on="doublet", quantity="pump_efficiency", max=bound, over=over)
    with raises(gm.errors.ValidationError, "invalid_value", match="parameter"):
        checked(constraint, plant=plant, results=make_results({"d0.esp": {"head": [1.0]}}))


def test_every_constraint_of_the_case_is_checked_in_order():
    """Two constraints, two checks."""
    found = checked(unmet(max=watts(9.0)), unmet(min=watts(0.0)))
    assert [item["passed"] for item in found] == [True, True]


def test_a_case_without_constraints_gives_no_checks():
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
    cooling = {"on": "doublet", "quantity": "brine_cooling", "max": Quantity(45, "K")}
    case = make_case(count=2, constraints=[gm.case.Constraint(**cooling)])
    assert gm.evaluate.constraints(plant, case, results)[0]["value"].value == 50.0
    case = make_case(count=2, constraints=[gm.case.Constraint(**cooling, when="running")])
    found = gm.evaluate.constraints(plant, case, results)[0]
    assert found["passed"] is True and found["value"].value == 40.0


def test_the_supply_temperature_of_a_service_is_a_requirement():
    """The heating consumer asks for at least 100 degC at its supply port, while it runs."""
    supply = {"heating": Quantity(100, "degC")}
    cold = make_results(
        {"heat": {"supply_in.temperature": [380.0, 360.0], "operating": [1.0, 1.0]}}
    )
    case = make_case(count=2, supply=supply)
    (found,) = gm.evaluate.constraints(heating_plant(), case, cold)
    assert found["name"] == "heat.supply_in.temperature"
    assert found["role"] == "heating_supply" and found["quantity"] == "temperature"
    assert found["passed"] is False and found["value"].value == 360.0
    assert found["limit"].value == pytest.approx(373.15)
    warm = make_results(
        {"heat": {"supply_in.temperature": [380.0, 375.0], "operating": [1.0, 1.0]}}
    )
    assert gm.evaluate.constraints(heating_plant(), case, warm)[0]["passed"] is True


def test_the_cooling_requirement_is_a_maximum_and_a_service_without_one_adds_nothing():
    """The cooling consumer asks for at most 20 degC; the heating service gives no temperature."""
    plant = heating_plant()
    plant._add_module("cool", gm.modules.CoolingGrid())
    results = make_results(
        {"cool": {"supply_in.temperature": [290.0, 295.0], "operating": [1.0, 1.0]}}
    )
    case = make_case(count=2, supply={"heating": None, "cooling": Quantity(20, "degC")})
    (found,) = gm.evaluate.constraints(plant, case, results)
    assert found["unit_path"] == "cool" and found["passed"] is False
    assert found["value"].value == 295.0 and found["limit"].value == pytest.approx(293.15)


def test_a_minimum_intake_pressure_rejects_a_design_whose_suction_drops_below_it():
    """The lowest intake pressure of a doublet is judged against the minimum of the case."""
    plant = gm.Plant("One")
    plant.add("Doublet", name="d0")
    results = make_results(
        {"d0.esp": {"intake_pressure": [30e5, 8e5, 25e5], "operating": [1.0, 1.0, 1.0]}}
    )
    low = gm.case.Constraint(on="doublet", quantity="intake_pressure", min=Quantity(10, "bar"))
    (found,) = checked(low, plant=plant, results=results)
    assert found["passed"] is False and found["name"] == "d0.esp.intake_pressure"
    assert found["value"].value == pytest.approx(8e5)
    held = gm.case.Constraint(on="doublet", quantity="intake_pressure", min=Quantity(5, "bar"))
    assert only(held, plant=plant, results=results)["passed"] is True


def test_a_maximum_gas_fraction_at_the_intake_is_judged_per_step():
    """The role reads the fraction of the gas volume at the pump intake."""
    plant = gm.Plant("One")
    plant.add("Doublet", name="d0")
    results = make_results(
        {"d0.esp": {"gas_volume_fraction": [0.02, 0.2], "operating": [1.0, 1.0]}}
    )
    limit = gm.case.Constraint(on="doublet", quantity="intake_gas_fraction", max=0.1)
    assert only(limit, plant=plant, results=results)["passed"] is False
