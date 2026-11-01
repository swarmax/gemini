"""Demand profiles built from a file, from values or from a frame, in the run-input format.

A profile is a frame with a UTC ``DatetimeIndex`` called ``time`` at a constant step, one column per
demand quantity in W, and ``attrs["units"]`` and ``attrs["quantities"]``: the demand of a
``gm.Case``. Every reader validates it the same way. It lives here because a ``gm.Case`` reads it
and ``gm.case`` imports no ``gm.data``, which exports ``from_csv`` and ``from_values``.
"""

import numpy as np
import pandas as pd

from gemini import units
from gemini._utils.strings import close_matches, did_you_mean, join_names
from gemini._utils.time import to_timedelta, to_utc, to_utc_index
from gemini.errors import RunError, ValidationError

QUANTITIES = {"heating_demand": "power", "cooling_demand": "power"}
"""The demand names a profile may hold, each with the quantity of its unit."""

SI_UNITS = {"power": "W"}
"""The SI unit a profile stores for each quantity."""


def from_csv(path, columns, unit, time_column=None):
    """Return the demand profile of a CSV file.

    Parameters
    ----------
    path : str or Path
        The file, with a header row.
    columns : dict
        ``{file column: quantity}``, each quantity a name of ``QUANTITIES``
        (``heating_demand`` or ``cooling_demand``).
    unit : str
        The unit of every value column, such as ``"MW"``; the profile stores W.
    time_column : str, optional
        The file column of the timestamps; the first column by default. Naive timestamps are UTC.

    Returns
    -------
    DataFrame
        UTC ``time`` index at a constant step, one column per quantity in W, with ``attrs["units"]``
        (``{column: "W"}``) and ``attrs["quantities"]`` (``{column: "power"}``). Any step and any
        length work.

    Raises
    ------
    ValidationError
        ``unknown_name`` for a quantity that is no demand, ``invalid_unit`` for a unit that is no
        power, ``missing_column`` for a column the file lacks, ``missing_value`` for an empty or
        non-numeric value, ``out_of_bounds`` for a negative one.
    RunError
        ``invalid_data`` for timestamps that are not monotonic, repeat, leave a gap or change step.
    """
    frame = pd.read_csv(path)
    time_column = frame.columns[0] if time_column is None else time_column
    wanted = [time_column, *columns]
    missing = [name for name in wanted if name not in frame]
    if missing:
        raise ValidationError(
            f"data.from_csv: column {missing[0]!r} not in {path}; expected one of "
            f"{join_names(frame.columns)}{did_you_mean(missing[0], frame.columns)}",
            path=missing[0],
            suggestions=close_matches(missing[0], frame.columns),
            code="missing_column",
        )
    values = {quantity: frame[name] for name, quantity in columns.items()}
    return _profile(_timestamps(frame[time_column]), values, dict.fromkeys(values, unit))


def from_values(values, unit, start, step, quantity):
    """Return the demand profile of one quantity from its values at a constant step.

    Parameters
    ----------
    values : sequence of float
        The demand at ``start``, ``start + step``, and so on.
    unit : str
        The unit of ``values``, such as ``"kW"``; the profile stores W.
    start : str or datetime
        The first timestamp; naive is UTC.
    step : str or float
        The duration between values, such as ``"1 h"`` or ``"1 d"``, or seconds.
    quantity : str
        ``heating_demand`` or ``cooling_demand``, the name of the column.

    Returns
    -------
    DataFrame
        As ``from_csv``, with one column.

    Raises
    ------
    ValidationError
        As ``from_csv``, and ``invalid_value`` for a ``step`` or ``start`` that is no duration or
        time.
    """
    try:
        interval = to_timedelta(step)
        first = to_utc(start)
    except (TypeError, ValueError) as error:
        raise ValidationError(
            f"data.from_values: step = {step!r}, start = {start!r}; expected a duration and "
            "an ISO-8601 time",
            code="invalid_value",
        ) from error
    index = pd.DatetimeIndex(pd.date_range(first, periods=len(values), freq=interval), name="time")
    return _profile(index, {quantity: pd.Series(list(values))}, {quantity: unit})


def _timestamps(column):
    """Return the UTC index of a column of timestamps."""
    try:
        return to_utc_index(column)
    except (TypeError, ValueError) as error:
        raise RunError(
            f"demand: time column = {column.name!r}; expected timestamps ({error})",
            code="invalid_data",
        ) from error


def _profile(index, values, column_units):
    """Return the validated frame of ``values`` on ``index`` in W, from ``{column: unit}``."""
    index = pd.DatetimeIndex(index, name="time")
    for quantity, unit in column_units.items():
        _checked_quantity(quantity, unit)
    _checked_index(index)
    data = {}
    for quantity, column in values.items():
        number = _checked_values(quantity, column)
        data[quantity] = units.array_convert(number, column_units[quantity], "W")
    frame = pd.DataFrame(data, index=index)
    frame.attrs["units"] = dict.fromkeys(data, "W")
    frame.attrs["quantities"] = {name: QUANTITIES[name] for name in data}
    return frame


def _checked_quantity(quantity, unit):
    """Raise unless ``quantity`` is a demand and ``unit`` a unit of its dimension."""
    if quantity not in QUANTITIES:
        raise ValidationError(
            f"demand: quantity = {quantity!r}; expected {join_names(QUANTITIES)}"
            f"{did_you_mean(quantity, QUANTITIES)}",
            path=str(quantity),
            suggestions=close_matches(quantity, QUANTITIES),
            code="unknown_name",
        )
    expected = SI_UNITS[QUANTITIES[quantity]]
    if units.si_unit(unit) != expected:
        raise ValidationError(
            f"demand: {quantity} unit = {unit!r}; expected a unit of {expected!r}",
            path=quantity,
            code="invalid_unit",
        )


def _checked_index(index):
    """Raise unless ``index`` is monotonic, without repeats or gaps, at a constant step."""
    if len(index) == 0 or index.hasnans:
        raise RunError("demand: time = empty or NaT; expected timestamps", code="invalid_data")
    steps = np.diff(index.asi8)
    problems = [
        (steps < 0, "increasing timestamps"),
        (steps == 0, "no repeated timestamp"),
        (steps != steps[:1], "a constant step, with no gap"),
    ]
    for found, expected in problems:
        if found.any():
            raise RunError(
                f"demand: time = {index[1:][found][0].isoformat()}; expected {expected}",
                code="invalid_data",
            )


def _checked_values(quantity, column):
    """Return the numbers of ``column``, or raise for a missing or negative one."""
    numbers = pd.to_numeric(column, errors="coerce").to_numpy(dtype=float)
    absent = np.isnan(numbers)
    if absent.any():
        raise ValidationError(
            f"demand: {quantity} row {int(absent.argmax())} is missing; expected a number",
            path=quantity,
            code="missing_value",
        )
    if (numbers < 0).any():
        raise ValidationError(
            f"demand: {quantity} row {int((numbers < 0).argmax())} = {numbers.min()}; "
            "expected zero or more",
            path=quantity,
            code="out_of_bounds",
        )
    return numbers
