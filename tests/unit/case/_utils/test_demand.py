"""``gm.data.from_csv`` and ``from_values``: demand profiles in the run-input format."""

import pandas as pd
import pytest

import gemini as gm
from tests.fixtures.errors import raises


def write(tmp_path, text):
    """Return the path of a CSV file holding ``text``."""
    path = tmp_path / "demand.csv"
    path.write_text(text)
    return path


def test_values_at_any_step_are_a_run_input_in_watts():
    """Hourly kW become W on a UTC index called time, with units and quantities."""
    frame = gm.data.from_values([1.0, 2.5, 0.0], "kW", "2030-03-01", "1 h", "heating_demand")
    assert frame.index.name == "time" and str(frame.index.tz) == "UTC"
    assert frame.index[2] == pd.Timestamp("2030-03-01 02:00", tz="UTC")
    assert frame["heating_demand"].tolist() == [1000.0, 2500.0, 0.0]
    assert frame.attrs["units"] == {"heating_demand": "W"}
    assert frame.attrs["quantities"] == {"heating_demand": "power"}
    assert len(gm.Dataset(frame)) == 3


def test_a_step_is_a_duration_text_or_seconds():
    """Daily as text and as seconds give the same index."""
    text = gm.data.from_values([1, 1], "W", "2030-01-01", "1 d", "cooling_demand")
    seconds = gm.data.from_values([1, 1], "W", "2030-01-01", 86400, "cooling_demand")
    assert text.index.equals(seconds.index)


def test_a_csv_maps_file_columns_to_quantities(tmp_path):
    """The first column is the time by default; columns keep the order given."""
    path = write(tmp_path, "day,h,c\n2030-01-01,3,1\n2030-01-02,4,2\n2030-01-03,5,3\n")
    frame = gm.data.from_csv(path, {"c": "cooling_demand", "h": "heating_demand"}, "MW")
    assert list(frame.columns) == ["cooling_demand", "heating_demand"]
    assert frame["heating_demand"].tolist() == [3e6, 4e6, 5e6]
    assert frame.index[0] == pd.Timestamp("2030-01-01", tz="UTC")


def test_a_csv_names_its_time_column(tmp_path):
    """Another column can carry the time; offsets convert to UTC."""
    path = write(tmp_path, "h,t\n1,2030-01-01T01:00:00+01:00\n2,2030-01-01T02:00:00+01:00\n")
    frame = gm.data.from_csv(path, {"h": "heating_demand"}, "W", time_column="t")
    assert frame.index[0] == pd.Timestamp("2030-01-01 00:00", tz="UTC")


def test_a_year_and_a_month_both_load(tmp_path):
    """No length is built in."""
    year = gm.data.from_values([1.0] * 365, "MW", "2031-01-01", "1 d", "heating_demand")
    month = gm.data.from_values([1.0] * 30 * 24, "MW", "2031-06-01", "1 h", "heating_demand")
    assert len(year) == 365 and len(month) == 720


def test_an_unknown_quantity_has_close_matches():
    """A misspelt quantity carries suggestions."""
    with raises(gm.errors.ValidationError, "unknown_name") as unknown:
        gm.data.from_values([1], "W", "2030-01-01", "1 d", "heating_demnd")
    assert unknown.value.suggestions[0] == "heating_demand"


@pytest.mark.parametrize("unit", ["m3/h", "megawatt"])
def test_a_unit_that_is_no_power_is_refused(unit):
    """A flow, or a unit that does not exist."""
    with raises(gm.errors.ValidationError, "invalid_unit"):
        gm.data.from_values([1], unit, "2030-01-01", "1 d", "heating_demand")


def test_a_missing_file_column_is_named(tmp_path):
    """The message lists the columns of the file."""
    path = write(tmp_path, "day,h\n2030-01-01,3\n")
    with raises(gm.errors.ValidationError, "missing_column", match="day, h"):
        gm.data.from_csv(path, {"x": "heating_demand"}, "W")
    with raises(gm.errors.ValidationError, "missing_column"):
        gm.data.from_csv(path, {"h": "heating_demand"}, "W", time_column="date")


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (["2030-01-02", "2030-01-01", "2030-01-03"], "increasing"),
        (["2030-01-01", "2030-01-01", "2030-01-02"], "repeated"),
        (["2030-01-01", "2030-01-02", "2030-01-04"], "constant step"),
        (["2030-01-01", "2030-01-03", "2030-01-04"], "constant step"),
    ],
)
def test_a_bad_time_index_is_refused(tmp_path, days, expected):
    """Order, repeats, gaps and a changing step."""
    rows = "".join(f"{day},1\n" for day in days)
    with raises(gm.errors.RunError, "invalid_data", match=expected):
        gm.data.from_csv(write(tmp_path, "t,h\n" + rows), {"h": "heating_demand"}, "W")


def test_text_that_is_no_time_is_refused(tmp_path):
    """The error names the column."""
    with raises(gm.errors.RunError, "invalid_data", match="'t'"):
        gm.data.from_csv(write(tmp_path, "t,h\nsoon,1\n"), {"h": "heating_demand"}, "W")


def test_no_rows_is_refused():
    """A profile of nothing is no profile."""
    with raises(gm.errors.RunError, "invalid_data"):
        gm.data.from_values([], "W", "2030-01-01", "1 d", "heating_demand")


@pytest.mark.parametrize("values", [[1.0, None], [1.0, float("nan")], [1.0, "x"]])
def test_a_missing_value_is_refused(values):
    """Empty, NaN and non-numeric values are missing."""
    with raises(gm.errors.ValidationError, "missing_value", match="row 1"):
        gm.data.from_values(values, "W", "2030-01-01", "1 d", "heating_demand")


def test_a_negative_value_is_refused():
    """Demand is zero or more."""
    with raises(gm.errors.ValidationError, "out_of_bounds", match="row 2"):
        gm.data.from_values([1.0, 0.0, -1.0], "W", "2030-01-01", "1 d", "heating_demand")


@pytest.mark.parametrize("step, start", [("soon", "2030-01-01"), (0, "2030-01-01"), (60, 5)])
def test_a_step_or_start_that_is_no_duration_or_time_is_refused(step, start):
    """Both are validated before the index is built."""
    with raises(gm.errors.ValidationError, "invalid_value"):
        gm.data.from_values([1.0], "W", start, step, "heating_demand")
