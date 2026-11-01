"""``gm.Case``: sections, SI storage, round trips, profiles and errors."""

import json

import numpy as np
import pandas as pd
import pytest

import gemini as gm
from tests.fixtures.errors import raises


def built(data, folder):
    """Return the case of ``data`` with its files in ``folder``."""
    return gm.Case.from_dict(data, folder)


def test_the_full_case_round_trips_through_a_dict_and_a_json_file(data, folder):
    """to_dict, from_dict, to_json and from_json give an equal case."""
    case = built(data, folder)
    target = folder / "out"
    target.mkdir()
    case.to_json(target / "case.json")
    assert gm.Case.from_dict(case.to_dict(), target) == case
    assert gm.Case.from_json(target / "case.json") == case
    assert sorted(path.name for path in target.iterdir()) == ["case.json", "demand.csv"]


def test_the_python_form_equals_the_json_form(data, folder):
    """The same case built from classes is equal to the one read from the dict."""
    from gemini.units import Quantity as Q

    python = gm.Case(
        time=gm.case.Time(start="2027-01-01", end="2027-01-08", step=Q(1, "d")),
        demand=gm.case.Demand(
            file=str(folder / "demand.csv"),
            time_column="date",
            heating=gm.case.Service(column="heat_MW", unit="MW", supply_temperature=Q(100, "degC")),
        ),
    )
    smaller = built({"time": data["time"], "demand": {**data["demand"], "cooling": None}}, folder)
    assert python.demand.frame.equals(smaller.demand.frame)
    assert python.time == smaller.time


def test_values_are_stored_in_si_and_written_in_si(data, folder):
    """12 degC is 285.15 K inside and in the file."""
    case = built(data, folder)
    assert case.environment.ground.surface_temperature == pytest.approx(285.15)
    assert case.demand.heating.supply_temperature == pytest.approx(373.15)
    written = case.to_dict()
    assert written["environment"]["ground"]["surface_temperature"] == {
        "value": pytest.approx(285.15),
        "unit": "K",
    }
    assert list(written) == [
        "time",
        "environment",
        "demand",
        "choices",
        "constraints",
        "assumptions",
    ]


def test_the_demand_frame_is_on_the_time_index(data, folder):
    """The frame is in W on the index of ``time``."""
    case = built(data, folder)
    assert case.demand.frame.index.equals(case.time.index)
    assert case.demand.frame["cooling_demand"].iloc[-1] == 2e6


def test_a_demand_off_the_time_range_names_the_file_and_the_row(data, folder):
    """One day of the file is missing from the time range."""
    data["time"]["end"] = "2027-01-09"
    with raises(gm.errors.ValidationError, "invalid_value") as caught:
        built(data, folder)
    assert "demand.csv" in str(caught.value) and "7 rows; expected 8" in str(caught.value)
    data["time"] = {"start": "2027-01-02", "end": "2027-01-09", "step": data["time"]["step"]}
    with raises(gm.errors.ValidationError, "invalid_value") as caught:
        built(data, folder)
    assert "row 0" in str(caught.value)


def test_a_profile_comes_from_a_csv_on_the_time_index(data, folder):
    """The air as a file column in degC becomes an array in K."""
    days = pd.date_range("2027-01-01", periods=7, freq="D")
    pd.DataFrame({"t": days, "t_air": np.arange(7.0)}).to_csv(folder / "air.csv", index=False)
    data["environment"]["air"] = {
        "temperature": {"file": "air.csv", "column": "t_air", "unit": "degC"}
    }
    case = built(data, folder)
    assert np.allclose(case.environment.air.temperature, 273.15 + np.arange(7.0))
    case.to_json(folder / "again.json")
    assert gm.Case.from_json(folder / "again.json") == case
    assert json.loads((folder / "again.json").read_text())["environment"]["air"]["temperature"][
        "file"
    ].endswith(".csv")


def test_a_profile_off_the_time_range_names_the_file_and_the_first_row(data, folder):
    """Row 3 of the profile is one day late."""
    days = pd.date_range("2027-01-01", periods=7, freq="D").to_series().reset_index(drop=True)
    days[3] = pd.Timestamp("2027-02-01")
    pd.DataFrame({"t": days, "p": np.ones(7)}).to_csv(folder / "price.csv", index=False)
    data["assumptions"]["finance"]["opex"]["gas"] = {
        "file": "price.csv",
        "column": "p",
        "unit": "EUR/MWh",
    }
    with raises(gm.errors.ValidationError, "invalid_value") as caught:
        built(data, folder)
    message = str(caught.value)
    assert "price.csv" in message and "row 3" in message and "opex.gas" in message


def test_an_array_of_the_wrong_length_is_invalid_value(data, folder):
    """A profile given as numbers must have one value per step."""
    data["assumptions"]["finance"]["opex"]["gas"] = {"value": [1.0, 2.0], "unit": "EUR/MWh"}
    with raises(gm.errors.ValidationError, "invalid_value") as caught:
        built(data, folder)
    assert "2 values; expected 7" in str(caught.value)


def test_a_missing_time_is_missing_value(data, folder):
    """The case needs its time."""
    del data["time"]
    with raises(gm.errors.ValidationError, "missing_value") as caught:
        built(data, folder)
    assert "time" in str(caught.value)


def test_an_unknown_section_and_key_are_unknown_name(data, folder):
    """Nothing outside the sections is accepted, and the error names the section."""
    data["problem"] = {}
    with raises(gm.errors.ValidationError, "unknown_name") as caught:
        built(data, folder)
    assert "problem" in str(caught.value)
    del data["problem"]
    data["environment"]["reservoir"]["depth"] = 1
    with raises(gm.errors.ValidationError, "unknown_name") as caught:
        built(data, folder)
    assert "environment.reservoir" in str(caught.value) and "reference_depth" in str(caught.value)


def test_an_error_names_the_path_in_the_case(data, folder):
    """A constraint bound of the wrong dimension names its index and field."""
    data["constraints"][0]["max"] = {"value": 300, "unit": "m"}
    with raises(gm.errors.ValidationError, "invalid_unit") as caught:
        built(data, folder)
    assert str(caught.value).startswith("constraints[0].max: unit 'm' is not a volume flow")
    assert caught.value.path == "constraints[0].max"


def test_text_and_plain_numbers_with_a_dimension_are_refused(data, folder):
    """A value with a dimension is a quantity."""
    data["environment"]["ground"]["gradient"] = "30 K/km"
    with raises(gm.errors.ValidationError, "invalid_value"):
        built(data, folder)
    data["environment"]["ground"]["gradient"] = 0.03
    with raises(gm.errors.ValidationError, "invalid_value"):
        built(data, folder)


def test_an_unreadable_json_is_invalid_format(tmp_path):
    """A missing file and a JSON that is no object."""
    with raises(gm.errors.ValidationError, "invalid_format"):
        gm.Case.from_json(tmp_path / "none.json")
    (tmp_path / "list.json").write_text("[]")
    with raises(gm.errors.ValidationError, "invalid_format"):
        gm.Case.from_json(tmp_path / "list.json")


def test_the_schema_is_closed_at_every_level():
    """``additionalProperties`` is false in every object of the schema."""
    schema = gm.Case.schema()
    open_objects = []

    def walk(node, path):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                if node.get("additionalProperties") is not False:
                    open_objects.append(path)
            for key, item in node.items():
                walk(item, f"{path}.{key}")
        elif isinstance(node, list):
            for number, item in enumerate(node):
                walk(item, f"{path}[{number}]")

    walk(schema, "case")
    assert open_objects == []
    assert list(schema["properties"]) == [
        "time",
        "environment",
        "demand",
        "choices",
        "constraints",
        "assumptions",
    ]
    assert schema["required"] == ["time"]


def test_a_case_with_only_a_time_is_valid():
    """Nothing but ``time`` is required; an absent section is ``None``."""
    case = gm.Case(
        time=gm.case.Time(start="2027-01-01", end="2027-01-02", step=gm.units.Quantity(1, "h"))
    )
    assert case.environment is None and case.constraints is None
    assert list(case.to_dict()) == ["time"]


def test_a_case_is_frozen(data, folder):
    """No attribute is set after the case is built."""
    case = built(data, folder)
    with pytest.raises(Exception):
        case.time = None
