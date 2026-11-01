"""One report of a finished run: its keys, its values and its plain JSON."""

import json

import pytest

import gemini as gm
from gemini.units import SECONDS_PER_YEAR, Quantity
from tests.fixtures.cases import costed_finance, make_case
from tests.fixtures.costed_plants import day, heating_plant

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
    assert plain["capex"]["unit"] == "currency" and plain["capex"]["value"] == 1000.0
    assert plain["constraints"][0]["role"] == "heating_supply"
    assert plain["failed_steps"] == 0
