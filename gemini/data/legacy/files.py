"""The semicolon CSV files of an old GEMINI project."""

from pathlib import Path

import pandas as pd

from gemini.errors import ValidationError
from gemini.plants._utils.legacy.project import OLD_TIME_FORMAT


def _from_times(column, path):
    """Parse old timestamps written as ``OLD_TIME_FORMAT`` or ISO 8601, never guessing order."""
    for time_format in (OLD_TIME_FORMAT, "ISO8601"):
        try:
            return pd.to_datetime(column, format=time_format)
        except (TypeError, ValueError):
            continue
    raise ValidationError(
        f"{path}: {column.name} = {column.iloc[0]!r}; expected {OLD_TIME_FORMAT} or ISO 8601",
        code="invalid_format",
    )


def from_csv(path):
    """Read an old semicolon CSV and parse its first column as timestamps."""
    path = Path(path)
    try:
        frame = pd.read_csv(path, sep=";", encoding="utf-8-sig")
    except (OSError, ValueError) as exc:
        raise ValidationError(f"{path}: invalid old CSV: {exc}", code="invalid_format") from exc
    if len(frame.columns):
        first = frame.columns[0]
        frame[first] = _from_times(frame[first], path)
    return frame


def to_csv(frame, path):
    """Write the old semicolon CSV with its conventional timestamp representation."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, sep=";", index=False, date_format=OLD_TIME_FORMAT)
