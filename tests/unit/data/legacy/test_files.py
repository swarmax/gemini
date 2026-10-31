"""The semicolon CSV files of an old project."""

import pandas as pd

from gemini.data import legacy
from gemini.errors import ValidationError
from tests.fixtures.errors import raises


def test_to_csv_applies_the_old_timestamp_format(tmp_path):
    """Midnight timestamps keep their time of day in the old CSV format."""
    frame = pd.DataFrame({"Timestamp": pd.to_datetime(["2024-01-01", "2024-01-02"]), "Q": [1, 2]})
    legacy.to_csv(frame, tmp_path / "old.csv")
    lines = (tmp_path / "old.csv").read_text(encoding="utf-8").splitlines()
    assert lines == ["Timestamp;Q", "2024-01-01 00:00:00;1", "2024-01-02 00:00:00;2"]


def test_from_csv_rejects_ambiguous_dates(tmp_path):
    """Day-first dates are not silently parsed month-first."""
    (tmp_path / "old.csv").write_text("Timestamp;Q\n07/06/2024;1\n", encoding="utf-8")
    with raises(ValidationError, "invalid_format", match="Timestamp"):
        legacy.from_csv(tmp_path / "old.csv")
    (tmp_path / "iso.csv").write_text("Timestamp;Q\n2024-06-07T01:00:00;1\n", encoding="utf-8")
    assert legacy.from_csv(tmp_path / "iso.csv").Timestamp[0] == pd.Timestamp("2024-06-07 01:00")


def test_a_frame_comes_back(tmp_path):
    """A frame written with ``to_csv`` reads back with ``from_csv``."""
    frame = pd.DataFrame({"Timestamp": pd.to_datetime(["2024-06-07 01:02:03"]), "Q": [1.5]})
    legacy.to_csv(frame, tmp_path / "old.csv")
    assert legacy.from_csv(tmp_path / "old.csv").Q.iloc[0] == 1.5
