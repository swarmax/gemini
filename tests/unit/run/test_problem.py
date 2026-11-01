"""``gm.Problem``: the one object of a demand, a site, constraints and assumptions."""

import json

import pandas as pd
import pytest

import gemini as gm
from gemini.errors import ValidationError
from tests.fixtures.errors import raises
from tests.fixtures.json_schema import check


def demand():
    """Return four hours of heating and cooling demand."""
    heat = gm.data.from_values([1, 2, 3, 4], "MW", "2027-01-01", "1 h", "heating_demand")
    cold = gm.data.from_values([0, 1, 0, 1], "kW", "2027-01-01", "1 h", "cooling_demand")
    return pd.concat([heat, cold], axis=1)


def problem():
    """Return a problem with every part."""
    return gm.Problem(
        demand(),
        {
            "d*.gradient": {"value": 30, "unit": "K/km"},
            "d*.surface_temperature": {"value": 12, "unit": "degC"},
        },
        [gm.Constraint("d*.brine_cooling", max={"value": 40, "unit": "K"})],
        gm.Assumptions(
            discount_rate=0.05,
            prices={"gas": gm.units.Quantity([1.0, 2.0, 3.0, 4.0], "currency/J")},
        ),
    )


def test_a_round_trip_keeps_every_part():
    """``to_dict`` is plain data in the shape ``from_values`` takes, and comes back equal."""
    data = problem().to_dict()
    assert data["demand"]["start"].startswith("2027-01-01T00:00:00")
    assert data["demand"]["step"] == 3600
    assert data["demand"]["units"] == {"heating_demand": "W", "cooling_demand": "W"}
    assert data["demand"]["values"]["heating_demand"] == [1e6, 2e6, 3e6, 4e6]
    again = gm.Problem.from_dict(data)
    assert again.to_dict() == data
    pd.testing.assert_frame_equal(again.demand, problem().demand, check_freq=False)


def test_the_dictionary_fits_the_schema():
    """The schema of ``schema`` accepts what ``to_dict`` gives."""
    assert check(problem().to_dict(), gm.Problem.schema()) == []


def test_a_demand_at_any_step_keeps_its_step():
    """A daily demand of two rows and one of one row round trip."""
    daily = gm.data.from_values([1, 2], "W", "2027-01-01", "1 d", "heating_demand")
    assert gm.Problem.from_dict(gm.Problem(daily).to_dict()).demand.index[1].day == 2
    single = gm.data.from_values([1], "W", "2027-01-01", "1 d", "heating_demand")
    assert len(gm.Problem.from_dict(gm.Problem(single).to_dict()).demand) == 1


@pytest.mark.parametrize(
    "arguments,code",
    [
        ({"demand": [1, 2]}, "invalid_value"),
        ({"demand": demand().tz_localize(None)}, "invalid_value"),
        ({"demand": demand(), "site": ["d0"]}, "invalid_value"),
        ({"demand": demand(), "site": {"d0.gradient": [1]}}, "invalid_value"),
        (
            {"demand": demand(), "site": {"d0.gradient": {"value": 1, "unit": "parsec"}}},
            "invalid_unit",
        ),
        ({"demand": demand(), "constraints": [{"path": "a.b"}]}, "invalid_value"),
        ({"demand": demand(), "assumptions": {}}, "invalid_value"),
        (
            {
                "demand": demand(),
                "assumptions": gm.Assumptions(
                    prices={"gas": gm.units.Quantity([1.0, 2.0], "currency/J")}
                ),
            },
            "invalid_value",
        ),
    ],
)
def test_each_part_is_validated(arguments, code):
    """A part of the wrong kind has its code."""
    with raises(ValidationError, code):
        gm.Problem(**arguments)


def test_a_demand_column_must_be_a_demand():
    """The columns are demand quantities, as ``from_csv`` makes them."""
    frame = demand().rename(columns={"heating_demand": "heat"})
    with raises(ValidationError, "unknown_name"):
        gm.Problem(frame)


def test_from_dict_names_what_is_wrong():
    """A dictionary without a demand, or with an unknown key, is refused with its code."""
    with raises(ValidationError, "missing_value"):
        gm.Problem.from_dict({})
    with raises(ValidationError, "unknown_name"):
        gm.Problem.from_dict({"demand": {}, "sites": {}})
    with raises(ValidationError, "missing_value", match="start"):
        gm.Problem.from_dict({"demand": {}})


def sited_plant():
    """Return a doublet with a depth that waits for its geotherm."""
    return gm.plants.Doublet().set_params("", {"depth": {"value": 2500, "unit": "m"}})


SITE = {
    "gradient": {"value": 30, "unit": "K/km"},
    "surface_temperature": {"value": 12, "unit": "degC"},
}


def test_the_site_goes_on_a_copy():
    """The copy has the geotherm and what it derives; the plant stays without it."""
    plant = sited_plant()
    sited = gm.Problem(demand(), SITE).apply_site(plant)
    assert sited is not plant and plant.gradient is None
    assert sited.gradient == pytest.approx(0.03)
    assert sited.reservoir.temperature == pytest.approx(285.15 + 75)


def test_a_problem_without_a_site_gives_the_plant_itself():
    """Nothing to apply: no copy, so traced graphs stay."""
    plant = sited_plant()
    assert gm.Problem(demand()).apply_site(plant) is plant


def test_a_star_reaches_every_match_and_a_deep_value_stands():
    """``d*`` reaches each doublet; a value below a doublet is not derived over."""
    plant = gm.Plant("Two")
    plant.add("Doublet", "d0").set_params("", {"depth": {"value": 2000, "unit": "m"}})
    plant.add("Doublet", "d1").set_params("", {"depth": {"value": 2000, "unit": "m"}})
    site = {
        "d*.gradient": {"value": 30, "unit": "K/km"},
        "d*.surface_temperature": {"value": 12, "unit": "degC"},
    }
    sited = gm.Problem(
        demand(), site | {"d1.reservoir.pressure": {"value": 100, "unit": "bar"}}
    ).apply_site(plant)
    assert sited.d0.gradient == sited.d1.gradient == pytest.approx(0.03)
    assert sited.d1.reservoir.pressure == pytest.approx(100e5)


def test_a_site_value_the_plant_states_is_refused():
    """The path names the parameter, not the pattern."""
    plant = sited_plant().set_params("", {"gradient": {"value": 20, "unit": "K/km"}})
    with raises(ValidationError, "conflicting_value", match="gradient"):
        gm.Problem(demand(), SITE).apply_site(plant)


def test_a_site_path_that_matches_nothing_is_refused():
    """A misspelled parameter is no silent no-op."""
    with raises(ValidationError, "unknown_name", match="gradient2"):
        gm.Problem(demand(), {"gradient2": 1}).apply_site(sited_plant())


def test_a_json_round_trip_keeps_every_part(tmp_path):
    """``to_json`` writes ``problem.json`` and ``demand.csv``; ``from_json`` reads them back."""
    problem().to_json(tmp_path / "problem.json")
    assert (tmp_path / "demand.csv").is_file()
    again = gm.Problem.from_json(tmp_path / "problem.json")
    assert again.to_dict() == problem().to_dict()
    pd.testing.assert_frame_equal(again.demand, problem().demand, check_freq=False)


def test_another_file_name_names_its_demand_file(tmp_path):
    """A file not called ``problem.json`` writes ``<stem>_demand.csv``."""
    problem().to_json(tmp_path / "other.json")
    assert (tmp_path / "other_demand.csv").is_file()
    assert gm.Problem.from_json(tmp_path / "other.json").to_dict() == problem().to_dict()


def test_a_json_demand_names_a_file_and_its_columns(tmp_path):
    """The demand is the arguments of ``from_csv`` around a file next to the JSON."""
    (tmp_path / "heat.csv").write_text("day,mw\n2027-01-01,2\n2027-01-02,3\n")
    spec = {"file": "heat.csv", "columns": {"mw": "heating_demand"}, "unit": "MW"}
    spec["time_column"] = "day"
    (tmp_path / "problem.json").write_text(json.dumps({"demand": spec}))
    found = gm.Problem.from_json(tmp_path / "problem.json")
    assert found.demand["heating_demand"].tolist() == [2e6, 3e6]


@pytest.mark.parametrize(
    "text,code",
    [
        (None, "invalid_format"),
        ("{", "invalid_format"),
        ("[1]", "invalid_format"),
        ("{}", "missing_value"),
        ('{"demand": {"columns": {}, "unit": "W"}}', "missing_value"),
        ('{"demand": {"file": "x.csv", "unit": "W"}}', "missing_value"),
        ('{"demand": {"file": "gone.csv", "columns": {}, "unit": "W"}}', "invalid_format"),
        ('{"demand": {"file": "x.csv", "columns": {}, "unit": "W"}, "sites": {}}', "unknown_name"),
    ],
)
def test_a_missing_or_malformed_json_has_its_code(tmp_path, text, code):
    """A file, a key or a demand file that is wrong is a ``ValidationError`` with a code."""
    if text is not None:
        (tmp_path / "problem.json").write_text(text)
    with raises(ValidationError, code):
        gm.Problem.from_json(tmp_path / "problem.json")
