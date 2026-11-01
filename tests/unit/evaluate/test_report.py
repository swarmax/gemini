"""One report of a finished run: its keys, its values and its plain JSON."""

import json

import pytest

import gemini as gm
from gemini.units import SECONDS_PER_YEAR, Quantity
from gemini.evaluate.report import Report
from tests.unit.evaluate.test_capacities import boiler_plant, boiler_run
from tests.fixtures.cases import costed_finance, make_case
from tests.fixtures.costed_plants import day, heating_plant
from tests.fixtures.result_tables import make_results

KEYS = {
    "heat_delivered",
    "cold_delivered",
    "boiler_heat",
    "electricity_bought",
    "gas_bought",
    "capacities",
    "capex",
    "opex",
    "lcts",
    "lcoh",
    "lcoc",
    "co2",
    "constraints",
    "passed",
    "failed_steps",
    "failures",
    "services",
}


def case(**parts):
    """Return a case with the finance of the costed plants and a limit on the unmet demand."""
    finance = costed_finance(
        opex={"electricity": Quantity(2e-8, "currency/J")},
        discount_rate=0.05,
        lifetime=Quantity(20, "yr"),
    )
    limit = gm.case.Constraint(on="heating_supply", quantity="unmet", max=Quantity(5.0, "W"))
    return make_case(
        finance=finance,
        constraints=[limit],
        emissions={"CO2": gm.case.CO2(electricity=Quantity(1e-7, "kg/J"))},
        **parts,
    )


def test_the_report_holds_the_energy_the_costs_the_checks_and_the_failed_steps():
    """Keys, quantities in Python and values of a day of 1000 W of heat."""
    report = gm.evaluate.report(heating_plant(), case(), day())
    assert set(report) == KEYS
    assert report["heat_delivered"].value == pytest.approx(1000.0 * 24 * 3600)
    assert report["capex"].value == 1000.0
    assert report["lcoh"].unit == "currency/J" and report["lcoh"].value > 0
    assert report["opex"].value == pytest.approx(10.0 + 2e-8 * 100.0 * SECONDS_PER_YEAR)
    assert report["co2"].value == pytest.approx(100.0 * 24 * 3600 * 1e-7)
    assert report["failed_steps"] == 0
    assert report["failures"].to_dict() == {"total": 0, "groups": []}
    assert report["boiler_heat"].value is None
    assert [item["name"] for item in report["constraints"]] == ["heat.unmet_demand"]
    assert report["passed"] is True


def test_a_cost_the_case_cannot_give_is_a_value_with_a_reason():
    """Without cooling the levelised cost of cold has no value, and the report still stands."""
    report = gm.evaluate.report(heating_plant(), case(), day())
    assert report["lcoc"].value is None and "no cold" in report["lcoc"].reason
    bare = gm.evaluate.report(heating_plant(), make_case(), day())
    assert bare["capex"].value is None and "assumptions.finance" in bare["capex"].reason


def test_to_dict_is_plain_json():
    """Every quantity is ``{value, unit}`` and the whole report dumps."""
    report = gm.evaluate.report(heating_plant(), case(), day())
    plain = report.to_dict()
    json.dumps(plain, allow_nan=False)
    assert plain["capex"]["unit"] == "MEUR" and plain["capex"]["value"] == pytest.approx(1e-3)
    assert report["capex"].value == 1000.0
    assert plain["constraints"][0]["role"] == "heating_supply"
    assert plain["failed_steps"] == 0


def test_a_boiler_the_run_does_not_show_gives_no_heat_value():
    """Boilers without port columns in the run leave the heat of the boilers unknown, not zero."""
    plant = gm.Plant("Boiling")
    plant.add("Boiler", "boiler")
    plant.boiler.capacity = Quantity(1e6, "W")
    results = make_results({"other": {"power_in": [1.0, 1.0]}})
    heat = gm.evaluate.report(plant, make_case(), results)["boiler_heat"]
    assert heat.value is None and "boilers" in heat.reason


def test_the_report_lists_the_services_the_case_asks_for():
    """No demand, no service; a heating demand is one."""
    assert gm.evaluate.report(heating_plant(), case(), day())["services"] == []
    asked = make_case(supply={"heating": Quantity(60, "degC")})
    assert gm.evaluate.report(heating_plant(), asked, day())["services"] == ["heating"]


def test_to_dict_shows_display_units_or_the_ones_given_and_the_report_stays_si():
    """Energy in MWh, power in MW; units replace one metric; the printed form is the display dict."""
    report = gm.evaluate.report(heating_plant(), case(), day())
    plain = report.to_dict()
    assert plain["heat_delivered"]["unit"] == "MWh"
    assert plain["heat_delivered"]["value"] == pytest.approx(0.024)
    assert plain["capacities"] == {}
    sized = Report(
        capacities=gm.evaluate.capacities(boiler_plant(), make_case(count=3), boiler_run())
    )
    boiler = sized.to_dict()["capacities"]["boiler"]
    assert boiler["capacity"] == {"value": pytest.approx(0.01), "unit": "MW"}
    assert boiler["share"]["unit"] == "-"
    given = report.to_dict(units={"heat_delivered": "GWh", "capex": "EUR"})
    assert given["heat_delivered"]["unit"] == "GWh" and given["capex"]["unit"] == "EUR"
    assert given["capex"]["value"] == pytest.approx(1000.0)
    assert report["heat_delivered"].unit == "J" and report["capex"].unit == "currency"
    assert json.loads(str(report)) == plain
    with pytest.raises(gm.errors.ValidationError):
        report.to_dict(units={"heat_delivered": "kt"})
