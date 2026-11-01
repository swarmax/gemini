"""Profiles of the case: a CSV column on the time index, read and written next to the JSON."""

from pathlib import Path

import numpy as np
import pandas as pd

from gemini._utils.time import to_utc_index
from gemini.errors import ValidationError

KEYS = {"file", "column", "unit"}
"""The keys of a profile in ``case.json``."""


def is_profile(value):
    """Whether ``value`` is the ``{"file", "column", "unit"}`` form of a profile."""
    return isinstance(value, dict) and set(value) == KEYS


def from_csv(spec, folder, index, path):
    """Return ``{"value": array, "unit": unit}`` of the profile ``spec`` of the case path ``path``.

    The file is read from ``folder``; its first column holds the timestamps, which must be
    ``index``: same start, step and number of rows.
    """
    file = Path(folder or ".") / spec["file"]
    if not file.is_file():
        raise ValidationError(
            f"{path}: profile file {str(file)!r} not found", path=path, code="invalid_format"
        )
    frame = pd.read_csv(file)
    if spec["column"] not in frame:
        raise ValidationError(
            f"{path}: column {spec['column']!r} not in {file.name}; expected one of "
            f"{', '.join(map(repr, frame.columns))}",
            path=path,
            code="missing_column",
        )
    check_index(to_utc_index(frame[frame.columns[0]]), index, file.name, path)
    values = pd.to_numeric(frame[spec["column"]], errors="coerce").to_numpy(dtype=float)
    if np.isnan(values).any():
        raise ValidationError(
            f"{path}: {file.name} row {int(np.isnan(values).argmax())} is missing; "
            "expected a number",
            path=path,
            code="missing_value",
        )
    return {"value": values, "unit": spec["unit"]}


def check_index(found, index, name, path):
    """Raise ``invalid_value`` naming ``name`` and the first row ``found`` that is not ``index``."""
    if len(found) != len(index):
        raise ValidationError(
            f"{path}: {name} has {len(found)} rows; expected {len(index)}, the steps of time",
            path=path,
            code="invalid_value",
        )
    differ = np.flatnonzero(found.asi8 != index.asi8)
    if len(differ):
        row = int(differ[0])
        raise ValidationError(
            f"{path}: {name} row {row} is {found[row].isoformat()}; expected "
            f"{index[row].isoformat()}, the step {row} of time",
            path=path,
            code="invalid_value",
        )


def to_csv(values, index, column, file):
    """Write ``values`` on ``index`` as the column ``column`` of the CSV ``file``."""
    frame = pd.DataFrame({column: np.asarray(values, dtype=float)}, index=index)
    frame.to_csv(file, index_label="time")
