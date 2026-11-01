"""Chunked time alignment of in-memory rows to finite ticks; it imports no engine code."""

from datetime import datetime, timedelta
from typing import NamedTuple

import numpy as np
import pandas as pd

from gemini._utils.time import DEFAULT_STEP, interval_seconds
from gemini.errors import RunError


class Sample(NamedTuple):
    """One row aligned to a tick; a stale hold or an empty mean bin is a row of NaN."""

    t: datetime
    dt: float
    row: dict


class Aligned:
    """The samples of a run as arrays: ``times``, ``durations`` and one array per column.

    ``numbers`` and ``present`` are the one conversion of a column to floats and the one rule of
    what is missing there; both are computed once per column.
    """

    def __init__(self, times, durations, columns):
        """Keep the aligned ``times``, their ``durations`` and the ``columns`` by name."""
        self.times, self.durations, self.columns = times, durations, columns
        self._numbers, self._present = {}, {}

    def numbers(self, column):
        """Return a column as floats; a value ``float()`` refuses (text, ``None``) is NaN."""
        if column not in self._numbers:
            self._numbers[column] = _floats(self.columns[column])
        return self._numbers[column]

    def present(self, column):
        """Return which rows of a column hold a value: one that is a finite number."""
        if column not in self._present:
            self._present[column] = np.isfinite(self.numbers(column))
        return self._present[column]

    def sample(self, index):
        """Return the ``Sample`` of one tick."""
        row = {name: values[index] for name, values in self.columns.items()}
        return Sample(self.times[index], float(self.durations[index]), row)


def _floats(values):
    """Return an array as floats; what ``float()`` refuses is NaN."""
    if values.dtype.kind == "f":
        return values
    numbers = np.full(len(values), np.nan)
    for index, value in enumerate(values):
        try:
            numbers[index] = float(value)
        except (TypeError, ValueError):
            continue
    return numbers


class _Window(NamedTuple):
    """The rows of the dataset inside one chunk: nanosecond times, the 2D values, numeric flags."""

    times: np.ndarray
    values: np.ndarray
    numeric: tuple


class Loader:
    """Align raw rows to any finite tick iterable with bounded source reads.

    ``align="previous"`` holds the latest row at or before each tick, ``"exact"`` requires a
    row at the tick itself and ``"mean"`` averages numeric values over ``[tick, next_tick)``,
    keeping the last text value. A hold older than ``max_gap`` is a gap; by default
    ``max_gap`` is twice the dataset's native cadence (``DEFAULT_STEP`` for fewer than two
    rows). ``durations`` gives the seconds from each tick to the next; by default they are
    the tick spacing followed by the native cadence. The dataset is read one ``chunk`` of
    ticks at a time.
    """

    def __init__(
        self,
        dataset,
        ticks,
        columns=None,
        align="previous",
        max_gap=None,
        chunk=timedelta(days=7),
        durations=None,
    ):
        """Validate the alignment options; reading starts on iteration."""
        if align not in {"exact", "previous", "mean"}:
            raise RunError(
                f"Loader: align = {align!r}; expected 'exact', 'previous' or 'mean'",
                code="invalid_data",
            )
        self.dataset, self.ticks, self.align = dataset, ticks, align
        self.columns = tuple(dataset.names if columns is None else columns)
        self.durations = durations
        self.max_gap = pd.Timedelta(
            max_gap if max_gap is not None else 2 * (dataset.native_step or DEFAULT_STEP)
        )
        self.chunk = pd.Timedelta(chunk)
        if self.max_gap < pd.Timedelta(0) or self.chunk <= pd.Timedelta(0):
            raise RunError(
                f"Loader: max_gap = {self.max_gap}, chunk = {self.chunk}; expected a "
                "nonnegative max_gap and a positive chunk",
                code="invalid_data",
            )

    def __iter__(self):
        """Yield one ``Sample`` per tick, built from the arrays of each chunk."""
        for block in self._blocks():
            for index in range(len(block.times)):
                yield block.sample(index)

    def arrays(self):
        """Return the samples of all ticks as ``Aligned`` arrays: the one alignment.

        Gaps are NaN, and a column array is ``float64`` unless the dataset holds text, when
        the arrays are ``object``.
        """
        blocks = list(self._blocks())
        if not blocks:
            return Aligned([], np.empty(0), {column: np.empty(0) for column in self.columns})
        times = [t for block in blocks for t in block.times]
        durations = np.concatenate([block.durations for block in blocks])
        columns = {c: np.concatenate([block.columns[c] for block in blocks]) for c in self.columns}
        return Aligned(times, durations, columns)

    def _blocks(self):
        """Yield the ``Aligned`` arrays of each chunk of ticks."""
        align = self._mean if self.align == "mean" else self._previous
        for window, stamps, times, seconds in self._windows():
            yield Aligned(times, np.asarray(seconds, dtype=float), align(window, stamps, seconds))

    def _windows(self):
        """Yield ``(window, stamps, times, seconds)`` of each chunk, from one read of the data.

        ``stamps`` are the ticks of the chunk as nanosecond integers and ``times`` as datetimes;
        ``window`` holds the rows of the dataset from ``max_gap`` before the first tick to the end
        of the last one, cut from the one conversion of the dataset to arrays.
        """
        ticks = pd.DatetimeIndex(list(self.ticks))
        if not len(ticks):
            return
        ticks = pd.to_datetime(ticks, utc=True).as_unit("ns")
        seconds = self.durations
        if seconds is None:
            seconds = interval_seconds(ticks, self.dataset.native_step or DEFAULT_STEP)
        frame = self.dataset.read(ticks[0] - self.max_gap, None, self.columns)
        rows = frame.index.as_unit("ns").asi8
        values = frame.to_numpy()
        numeric = tuple(pd.api.types.is_numeric_dtype(dtype) for dtype in frame.dtypes)
        stamps = ticks.asi8
        times = [t.to_pydatetime() for t in ticks]
        for offset, stop in self._chunks(stamps):
            end = stamps[stop - 1] + pd.Timedelta(seconds=float(seconds[stop - 1])).value
            left = np.searchsorted(rows, stamps[offset] - self.max_gap.value, side="left")
            right = np.searchsorted(rows, end, side="right")
            window = _Window(rows[left:right], values[left:right], numeric)
            yield window, stamps[offset:stop], times[offset:stop], seconds[offset:stop]

    def _chunks(self, stamps):
        """Yield ``(offset, stop)`` positions of consecutive tick chunks of at most ``chunk``."""
        offset = 0
        while offset < len(stamps):
            limit = stamps[offset] + self.chunk.value
            stop = max(offset + 1, np.searchsorted(stamps, limit, side="left"))
            yield offset, stop
            offset = stop

    def _previous(self, window, stamps, seconds):
        """Hold the latest row at or before each tick (``exact``: only a row at the tick).

        Row times are compared as nanosecond integers, the unit of ``Timestamp.value``, whatever
        the resolution of the dataset index (pandas 3 parses text as microseconds).
        """
        held, gaps = self._hold(window, stamps)
        held[gaps] = np.nan
        return {column: held[:, index] for index, column in enumerate(self.columns)}

    def _positions(self, window, stamps):
        """Return the held row position of each tick and whether the tick is a gap.

        A tick is a gap without a row at or before it, when the hold is older than ``max_gap``
        or, for ``exact`` alignment, when the row is not at the tick itself.
        """
        times = window.times
        positions = np.searchsorted(times, stamps, side="right") - 1
        if not len(times):
            return positions, np.ones(len(stamps), dtype=bool)
        held = times[positions]
        gaps = (positions < 0) | (stamps - held > self.max_gap.value)
        if self.align == "exact":
            gaps |= held != stamps
        return positions, gaps

    def _hold(self, window, stamps):
        """Return the held rows as one 2D array (a copy) and the gap mask."""
        positions, gaps = self._positions(window, stamps)
        values = window.values
        if values.dtype.kind in "iub":
            values = values.astype(float)
        if not len(values):
            return np.full((len(stamps), len(self.columns)), np.nan), gaps
        return values[positions], gaps

    def _mean(self, window, stamps, seconds):
        """Average each numeric column over ``[tick, tick + dt)``; text keeps its last value."""
        times, values, numeric = window
        starts = stamps
        lefts = np.searchsorted(times, starts, side="left")
        lengths = np.round(np.asarray(seconds) * 1e9).astype(np.int64)
        rights = np.searchsorted(times, starts + lengths, side="left")
        bins = [
            [
                _bin_value(values[left:right, index], is_numeric)
                for left, right in zip(lefts, rights)
            ]
            for index, is_numeric in enumerate(numeric)
        ]
        return {column: _column(bin_values) for column, bin_values in zip(self.columns, bins)}


def _column(values):
    """Return ``values`` as a ``float64`` array, or as an ``object`` array when any is text."""
    array = np.array(values, dtype=object)
    try:
        return array.astype(float)
    except (TypeError, ValueError):
        return array


def _bin_value(column, is_numeric):
    """Return the mean of a numeric bin with finite values, else its last value or NaN."""
    if is_numeric and np.isfinite(column.astype(float)).any():
        return np.nanmean(column.astype(float))
    return column[-1] if len(column) else np.nan
