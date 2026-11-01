"""The assumptions object: sourced defaults only, everything else the user's."""

import pytest
from pydantic import ValidationError as FieldError

import gemini as gm
from gemini.run import assumptions as module
from gemini.run.assumptions import COST_SOURCES, Assumptions
from tests.fixtures.errors import raises


def test_only_the_sourced_defaults_are_set():
    """Every value nobody gave has a source; the others are ``None`` until the user gives them."""
    given = Assumptions().model_dump()
    assert given["currency"] == "EUR"
    assert given["methane_gwp"] == 29.8
    assert given["cost_price_year"] == 2015
    assert all(given[name] is not None for name in COST_SOURCES)
    assert [name for name, value in given.items() if value is None] == [
        "discount_rate",
        "lifetime_years",
        "co2_price",
        "electricity_emission_factor",
        "heat_cost_share",
        "pump_cost",
        "chiller_cost",
        "exchanger_cost",
        "flare_cost",
        "makeup_cost",
    ]


def test_a_factor_says_where_it_comes_from():
    """A default cites its source; a factor the user gives is the user's."""
    assert "SDE+" in Assumptions().source_of("drilling_cost")
    assert (
        Assumptions(boiler_cost=gm.units.Quantity(0.1, "currency/W")).source_of("boiler_cost")
        == "assumptions.boiler_cost"
    )
    assert Assumptions().factor("boiler_cost") == 0.06
    with pytest.raises(gm.errors.ValidationError, match="pump_cost") as error:
        Assumptions().factor("pump_cost")
    assert error.value.code == "missing_assumption"


def test_the_object_is_frozen_strict_and_checked():
    """A value cannot change, an unknown name is refused and a negative price is invalid."""
    values = Assumptions(discount_rate=0.05)
    with pytest.raises(FieldError):
        values.discount_rate = 0.1
    with raises(gm.errors.ValidationError, "unknown_name"):
        Assumptions(discount_rat=0.05)


def test_resolve_gives_the_defaults_for_none_and_refuses_other_types():
    """``None`` means the defaults; anything but an Assumptions is a validation error."""
    assert module.resolve(None) == Assumptions()
    with pytest.raises(gm.errors.ValidationError, match="Assumptions"):
        module.resolve({"discount_rate": 0.05})


def test_require_names_the_missing_assumption():
    """A value the user must give raises with the code the backend lists."""
    with pytest.raises(gm.errors.ValidationError, match="discount_rate") as error:
        module.require(Assumptions(), "discount_rate")
    assert error.value.code == "missing_assumption"
    assert error.value.path == "assumptions.discount_rate"
    assert module.require(Assumptions(discount_rate=0.05), "discount_rate") == 0.05


def test_discounting_prefers_the_arguments_and_checks_them():
    """An explicit rate and lifetime win; a lifetime under one year is refused."""
    values = Assumptions(discount_rate=0.05, lifetime_years=20)
    assert module.discounting(values, None, None) == (0.05, 20)
    assert module.discounting(values, 0.0, 10) == (0.0, 10)
    with pytest.raises(gm.errors.ValidationError, match="lifetime"):
        module.discounting(values, None, 0)
    with pytest.raises(gm.errors.ValidationError, match="discount_rate"):
        module.discounting(values, -0.1, None)


def test_a_round_trip_keeps_the_values():
    """``from_dict`` of ``to_dict`` gives the same assumptions, and only what differs is stored."""
    values = Assumptions(
        discount_rate=0.05,
        prices={"gas": {"value": 40, "unit": "EUR/MWh"}},
        co2_price={"value": 80, "unit": "EUR/t"},
    )
    assert values.to_dict() == {
        "discount_rate": 0.05,
        "prices": {"gas": {"value": 40, "unit": "EUR/MWh"}},
        "co2_price": {"value": 80, "unit": "EUR/t"},
    }
    assert Assumptions.from_dict(values.to_dict()) == values


def test_the_schema_describes_the_fields():
    """The schema is plain JSON and names the new fields."""
    properties = Assumptions.schema()["properties"]
    assert {"prices", "co2_price", "discount_rate"} <= set(properties)


def test_a_price_is_a_quantity_a_dict_or_a_profile():
    """Every form gives SI numbers."""
    values = Assumptions(
        prices={
            "electricity": gm.units.Quantity(2e-8, "currency/J"),
            "gas": {"value": 36, "unit": "EUR/MWh"},
            "heat": gm.units.Quantity([1.0, 2.0], "currency/J"),
            "cold": {"value": [3.6, 7.2], "unit": "EUR/MWh"},
            "chemical": {"value": 3, "unit": "EUR/kg"},
        },
        co2_price={"value": 80, "unit": "EUR/t"},
    )
    assert values.price("electricity") == 2e-8
    assert values.price("gas") == pytest.approx(1e-8)
    assert values.price("heat").tolist() == [1.0, 2.0]
    assert values.price("cold") == pytest.approx([1e-9, 2e-9])
    assert values.price("chemical") == 3.0
    assert values.co2_cost() == pytest.approx(0.08)


def test_a_missing_price_names_the_carrier():
    """Nobody gave it: ``missing_assumption``, or ``None`` when it is not required."""
    with raises(gm.errors.ValidationError, "missing_assumption", match="prices.gas"):
        Assumptions().price("gas")
    assert Assumptions().price("gas", required=False) is None


@pytest.mark.parametrize(
    "fields,code",
    [
        ({"discount_rate": -1}, "out_of_bounds"),
        ({"heat_cost_share": 2}, "out_of_bounds"),
        ({"discount": 0.05}, "unknown_name"),
        ({"lifetime_years": "long"}, "invalid_value"),
        ({"prices": {"steam": {"value": 1, "unit": "EUR/MWh"}}}, "unknown_name"),
        ({"prices": {"gas": {"value": 1, "unit": "EUR/kg"}}}, "invalid_unit"),
        ({"co2_price": {"value": 1, "unit": "EUR/MWh"}}, "invalid_unit"),
    ],
)
def test_a_field_is_refused_with_its_code(fields, code):
    """What pydantic and the prices refuse is a ``gm.errors`` code."""
    with raises(gm.errors.ValidationError, code):
        Assumptions(**fields)
