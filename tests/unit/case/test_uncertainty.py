"""The ``uncertainty`` of a value of the case: parsing, validation, SI storage and round trip."""

import copy

import pytest

import gemini as gm
from tests.fixtures.errors import raises
from tests.unit.case.test_case import built

ELECTRICITY = "assumptions.finance.opex.electricity"
UNIFORM = {"kind": "uniform", "min": 80, "max": 140}


def declared(data, section, *path, **uncertainty):
    """Return ``data`` with an ``uncertainty`` set on the value at ``section``/``path``."""
    data = copy.deepcopy(data)
    node = data[section]
    for part in path:
        node = node[part]
    node["uncertainty"] = uncertainty
    return data


def electricity(data, **uncertainty):
    """Return ``data`` with an uncertainty on the electricity price (100 EUR/MWh)."""
    return declared(data, "assumptions", "finance", "opex", "electricity", **uncertainty)


def test_a_case_without_uncertainty_has_none(data, folder):
    """The mapping is empty and nothing is written."""
    case = built(data, folder)
    assert case.uncertainty is None and "uncertainty" not in str(case.to_dict())


def test_uniform_is_stored_in_si_and_the_value_is_unchanged(data, folder):
    """The bounds are in the unit of the value and become currency/J."""
    case = built(electricity(data, **UNIFORM), folder)
    found = case.uncertainty[ELECTRICITY]
    assert found.kind == "uniform"
    assert found.min == pytest.approx(80 / 3.6e9) and found.max == pytest.approx(140 / 3.6e9)
    assert found.std is None
    assert case.assumptions.finance.opex.electricity == pytest.approx(100 / 3.6e9)


def test_triangular_and_normal_with_and_without_bounds(data, folder):
    """The mode is the value; a normal needs a std and may be truncated."""
    triangular = built(electricity(data, kind="triangular", min=60, max=200), folder)
    assert triangular.uncertainty[ELECTRICITY].kind == "triangular"
    normal = built(electricity(data, kind="normal", std=10), folder)
    assert normal.uncertainty[ELECTRICITY].std == pytest.approx(10 / 3.6e9)
    assert normal.uncertainty[ELECTRICITY].min is None
    cut = built(electricity(data, kind="normal", std=10, min=50, max=150), folder)
    assert cut.uncertainty[ELECTRICITY].max == pytest.approx(150 / 3.6e9)


def test_a_dimensionless_value_and_an_offset_unit(data, folder):
    """A bare number carries an uncertainty next to it; a std ignores a unit offset."""
    rate = copy.deepcopy(data)
    rate["assumptions"]["finance"]["discount_rate"] = {
        "value": 0.05,
        "uncertainty": {"kind": "normal", "std": 0.01, "min": 0.02, "max": 0.1},
    }
    case = built(rate, folder)
    assert case.assumptions.finance.discount_rate == 0.05
    assert case.uncertainty["assumptions.finance.discount_rate"].std == 0.01
    assert case.to_dict()["assumptions"]["finance"]["discount_rate"]["value"] == 0.05
    air = declared(data, "environment", "air", "temperature", kind="normal", std=2)
    found = built(air, folder).uncertainty["environment.air.temperature"]
    assert found.std == pytest.approx(2.0)


def test_the_dict_and_the_json_round_trip(data, folder):
    """to_dict writes the uncertainty back next to the value, in SI."""
    case = built(electricity(data, **UNIFORM), folder)
    written = case.to_dict()["assumptions"]["finance"]["opex"]["electricity"]
    assert written["uncertainty"] == {
        "kind": "uniform",
        "min": pytest.approx(80 / 3.6e9),
        "max": pytest.approx(140 / 3.6e9),
    }
    target = folder / "out"
    target.mkdir()
    case.to_json(target / "case.json")
    assert gm.Case.from_dict(case.to_dict(), target) == case
    assert gm.Case.from_json(target / "case.json") == case


@pytest.mark.parametrize(
    ("uncertainty", "code", "text"),
    [
        ({}, "missing_value", "kind"),
        ({"kind": "beta"}, "unknown_name", "kind"),
        ({"kind": "uniform", "min": 80}, "missing_value", "max"),
        ({"kind": "uniform", "min": 80, "max": 140, "std": 1}, "unknown_name", "std"),
        ({"kind": "normal"}, "missing_value", "std"),
        ({"kind": "normal", "std": 0}, "out_of_bounds", "std"),
        ({"kind": "uniform", "min": 80, "max": 140, "mean": 1}, "unknown_name", "mean"),
        ({"kind": "uniform", "min": 110, "max": 140}, "out_of_bounds", "min"),
        ({"kind": "triangular", "min": 80, "max": 90}, "out_of_bounds", "max"),
        ({"kind": "uniform", "min": 140, "max": 80}, "out_of_bounds", "min"),
        ({"kind": "uniform", "min": -10, "max": 140}, "out_of_bounds", "min"),
        ({"kind": "uniform", "min": "80", "max": 140}, "invalid_value", "min"),
    ],
)
def test_an_uncertainty_that_does_not_fit_names_its_path(data, folder, uncertainty, code, text):
    """Kind, required keys, unknown keys, value inside the range and the bounds of the field."""
    with raises(gm.errors.ValidationError, code) as caught:
        built(electricity(data, **uncertainty), folder)
    assert caught.value.path.startswith(f"{ELECTRICITY}.uncertainty")
    assert text in str(caught.value)


@pytest.mark.parametrize("section", ["time", "demand", "choices", "constraints"])
def test_other_sections_cannot_carry_uncertainty(data, folder, section):
    """An uncertainty below time, demand, choices or constraints is refused with its path."""
    data = copy.deepcopy(data)
    node = data[section][0] if section == "constraints" else data[section]
    node["uncertainty"] = UNIFORM
    with raises(gm.errors.ValidationError, "invalid_value") as caught:
        built(data, folder)
    assert caught.value.path.startswith(section)


def test_a_profile_cannot_carry_uncertainty(data, folder):
    """Only a number does."""
    data = electricity(data, **UNIFORM)
    data["assumptions"]["finance"]["opex"]["electricity"]["value"] = [1.0] * 7
    with raises(gm.errors.ValidationError, "invalid_value"):
        built(data, folder)


def test_the_schema_accepts_the_uncertainty_next_to_a_value():
    """The closed schema allows the key in the environment and the assumptions only."""
    price = gm.Case.schema()["properties"]["assumptions"]["properties"]["finance"]
    price = price["properties"]["opex"]["properties"]["electricity"]
    assert price["properties"]["uncertainty"]["properties"]["kind"]["enum"] == [
        "uniform",
        "triangular",
        "normal",
    ]
    limit = gm.Case.schema()["properties"]["choices"]["properties"]["depth"]
    assert "uncertainty" not in str(limit)
