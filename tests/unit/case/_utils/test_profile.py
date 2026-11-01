"""Profiles of the case: CSV columns on the time index."""

import numpy as np
import pandas as pd
import pytest

import gemini as gm
from gemini.case._utils import profile
from tests.fixtures.errors import raises

INDEX = pd.date_range("2027-01-01", periods=3, freq="D", tz="UTC", name="time")


def write(folder, times, name="p.csv"):
    """Write a profile file with the given timestamps and the values 1, 2, 3."""
    pd.DataFrame({"t": times, "v": [1.0, 2.0, 3.0]}).to_csv(folder / name, index=False)


def test_the_form_of_a_profile():
    """Exactly file, column and unit."""
    assert profile.is_profile({"file": "a.csv", "column": "b", "unit": "K"})
    assert not profile.is_profile({"value": 1, "unit": "K"})


def test_a_column_on_the_index_is_read(tmp_path):
    """The values come with their unit."""
    write(tmp_path, INDEX.tz_localize(None))
    found = profile.from_csv({"file": "p.csv", "column": "v", "unit": "K"}, tmp_path, INDEX, "x")
    assert found["unit"] == "K" and list(found["value"]) == [1.0, 2.0, 3.0]


def test_a_missing_file_and_a_missing_column(tmp_path):
    """``invalid_format`` and ``missing_column``."""
    with raises(gm.errors.ValidationError, "invalid_format"):
        profile.from_csv({"file": "no.csv", "column": "v", "unit": "K"}, tmp_path, INDEX, "x")
    write(tmp_path, INDEX.tz_localize(None))
    with raises(gm.errors.ValidationError, "missing_column"):
        profile.from_csv({"file": "p.csv", "column": "w", "unit": "K"}, tmp_path, INDEX, "x")


def test_a_gap_in_the_values_is_missing_value(tmp_path):
    """An empty cell is refused."""
    (tmp_path / "p.csv").write_text("t,v\n2027-01-01,1\n2027-01-02,\n2027-01-03,3\n")
    with raises(gm.errors.ValidationError, "missing_value") as caught:
        profile.from_csv({"file": "p.csv", "column": "v", "unit": "K"}, tmp_path, INDEX, "x")
    assert "row 1" in str(caught.value)


def test_the_first_row_that_differs_is_named():
    """A shifted row and a wrong length."""
    shifted = INDEX.delete(1).insert(1, pd.Timestamp("2027-03-01", tz="UTC"))
    with raises(gm.errors.ValidationError, "invalid_value") as caught:
        profile.check_index(shifted, INDEX, "p.csv", "path")
    assert "p.csv row 1" in str(caught.value)
    with raises(gm.errors.ValidationError, "invalid_value") as caught:
        profile.check_index(INDEX[:2], INDEX, "p.csv", "path")
    assert "2 rows; expected 3" in str(caught.value)


def test_a_profile_is_written_with_its_time_column(tmp_path):
    """The file has a ``time`` column and the named value column."""
    profile.to_csv(np.array([1.0, 2.0, 3.0]), INDEX, "v", tmp_path / "out.csv")
    frame = pd.read_csv(tmp_path / "out.csv")
    assert list(frame.columns) == ["time", "v"] and frame["v"].tolist() == [1.0, 2.0, 3.0]
    assert pytest.approx(frame["v"].sum()) == 6.0
