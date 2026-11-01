"""Chunks of ticks committed to ``Results``, and their assembly into one table.

A chunk holds the ticks of one evaluation as columns. Whatever its length, one tick or a whole
window, it goes through the same code. Columns are NumPy arrays or, for objects such as list
outputs, Python lists; the table built from several chunks is lazy.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from gemini.errors import ValidationError
from gemini.types.flows import Stream

ADDED_QUANTITIES = (
    "mass_flow",
    "volume_flow",
    "enthalpy_flow",
    "gas_flow",
    "co2_flow",
    "chemical_flow",
)
"""The quantities of a fluid port that add up over the streams of a ``many`` port."""

MISSING = float("nan")
"""What a row without a path holds in an object column, as an absent key of a row dict did."""


@dataclass(eq=False)
class PathColumns:
    """The fields of one module path over the ticks of a chunk.

    ``present`` is a boolean array over the ticks: the rows this path was evaluated for. Every
    column has one entry per tick, whether present or not; entries of absent rows are ignored.
    A column is a NumPy array (a 2-D array holds one list per row) or a Python list for
    objects such as list outputs and message strings. Columns are kept by reference.
    """

    present: np.ndarray
    columns: dict
    complete: bool = field(init=False)

    def __post_init__(self):
        """Normalise the mask and remember whether every tick is present."""
        self.present = np.asarray(self.present, dtype=bool)
        self.complete = bool(self.present.all())

    @classmethod
    def of(cls, result, health, present):
        """Return the columns of a leaf ``ModuleResult`` of arrays and its ``Health`` of arrays.

        Scalars broadcast over the ticks; a Python list is a column. ``operating`` is computed
        from the flows of the ports: any port with a non-zero mass flow, or no port at all.
        """
        length = len(present)
        columns = _result_columns(result, health, length)
        return cls(present, columns)

    def sliced(self, start, stop):
        """Return the ticks ``start:stop``."""
        columns = {name: values[start:stop] for name, values in self.columns.items()}
        return PathColumns(self.present[start:stop], columns)

    def without(self, ticks):
        """Return these columns with the ticks at the positions ``ticks`` marked absent."""
        if not len(ticks):
            return self
        present = self.present.copy()
        present[ticks] = False
        return PathColumns(present, self.columns)

    def spread(self, ticks, size):
        """Return the columns of ``size`` ticks whose entries sit at the positions ``ticks``.

        The columns of this object have one entry per evaluated row; the other ticks are absent.
        """
        present = np.zeros(size, dtype=bool)
        present[ticks] = True
        return PathColumns(
            present, {name: _spread(values, ticks, size) for name, values in self.columns.items()}
        )


def _spread(values, ticks, size):
    """Return a column of ``size`` entries holding ``values`` at ``ticks``."""
    if len(ticks) == size:
        return values
    if isinstance(values, list):
        full = [None] * size
        for tick, value in zip(ticks, values):
            full[tick] = value
        return full
    shape = (size, *values.shape[1:])
    full = np.full(shape, np.nan) if values.dtype.kind == "f" else np.zeros(shape, values.dtype)
    full[ticks] = values
    return full


def _result_columns(result, health, length):
    """Return the output, ``operating`` and health columns of a path, in the row order."""
    columns = {
        name: _column(_with_none(value, result.outputs.accepts_none(name)), length)
        for name, value in result.outputs.items()
    }
    columns["operating"] = _operating(result, length)
    for name, port in (*result.inlets.items(), *result.outlets.items()):
        columns.update(_port_columns(name, port, length))
    if health is None:
        return columns
    columns["health_assessed"] = _column(health.assessed, length)
    columns["health_score"] = _column(_number(health.score), length)
    columns["health_alarm"] = _column(health.alarm, length)
    columns["health_message"] = _column(health.message, length)
    for name, value in health.metrics.items():
        columns["health_metric_" + name] = _column(_number(value), length)
    return columns


def _port_columns(name, value, length):
    """Return the columns of one port: its power, or the quantities of its stream.

    A ``many`` port holds a list: its flows add up, and it has no one temperature or pressure.
    """
    items = value if isinstance(value, list) else [value]
    if not items or not isinstance(items[0], Stream):
        return {name: _broadcast(sum(items, start=0.0), length)}
    quantities = [item.quantities() for item in items]
    if isinstance(value, list):
        return {
            f"{name}.{key}": _broadcast(sum(item[key] for item in quantities), length)
            for key in ADDED_QUANTITIES
        }
    return {f"{name}.{key}": _broadcast(item, length) for key, item in quantities[0].items()}


def _broadcast(value, length):
    """Return a port value as a float array of ``length`` ticks."""
    return np.broadcast_to(np.asarray(value, dtype=float), (length,))


def _number(value):
    """Return a health score or metric as ``float`` or a float array, as the Python backend does."""
    if np.ndim(value) == 0:
        return float(value)
    return np.asarray(value, dtype=float)


def _with_none(value, nullable):
    """Return a declared ``X | None`` float array with NaN as a list with ``None``, else as is."""
    if not (nullable and isinstance(value, np.ndarray) and value.dtype.kind == "f"):
        return value
    if value.ndim != 1 or not np.isnan(value).any():
        return value
    return [None if item != item else item for item in value.tolist()]


def _operating(result, length):
    """Return, per tick, whether any port carries flow; a module without ports is operating."""
    ports = [*result.inlets.values(), *result.outlets.values()]
    flows = [port for port in ports if isinstance(port, Stream)]
    if not flows:
        return np.ones(length, dtype=bool)
    moving = [np.broadcast_to(np.asarray(flow.m_dot) != 0, (length,)) for flow in flows]
    return np.logical_or.reduce(moving)


def _column(value, length):
    """Return ``value`` as a column of ``length`` ticks: arrays and lists as they are."""
    if isinstance(value, np.ndarray) and value.ndim:
        return value
    if isinstance(value, list):
        return value
    if isinstance(value, (float, int, np.generic)):
        return np.full(length, value)
    return [value] * length


@dataclass(eq=False)
class ResultChunk:
    """A chunk of ticks, ready to be committed with ``Results.commit``.

    ``times`` are the tick timestamps and ``durations`` the seconds each tick integrates.
    ``tables`` maps a module path to its ``PathColumns``. ``skips`` holds one
    ``{path: {reason: count}}`` mapping per tick (or ``None`` for no skip) and ``errors`` the
    ``(tick index, {"module", "message", "type"})`` pairs of the failing rows.
    """

    times: object
    durations: object
    tables: dict
    skips: list | None = None
    errors: object = ()

    def __post_init__(self):
        """Check that every sequence has one entry per tick."""
        size = len(self.times)
        sizes = {"durations": len(self.durations)}
        if self.skips is not None:
            sizes["skips"] = len(self.skips)
        for path, table in self.tables.items():
            sizes[f"{path}.present"] = len(table.present)
            sizes.update({f"{path}.{name}": len(col) for name, col in table.columns.items()})
        wrong = {name: length for name, length in sizes.items() if length != size}
        if wrong:
            name, length = next(iter(wrong.items()))
            raise ValidationError(
                f"ResultChunk: {name} has {length} entries; expected one per tick ({size})",
                code="invalid_call",
            )

    def __len__(self):
        """Count the ticks."""
        return len(self.times)

    def column_order(self):
        """Return the ``(path, field)`` keys in the order a row-by-row build first meets them.

        Paths are ordered by the first tick they are present, then as given; fields as given.
        """
        first = {path: first_present(table) for path, table in self.tables.items()}
        paths = sorted((path for path in self.tables if first[path] is not None), key=first.get)
        return [(path, name) for path in paths for name in self.tables[path].columns]

    def rows(self, start, stop):
        """Return the ticks ``start:stop``."""
        return ResultChunk(
            self.times[start:stop],
            self.durations[start:stop],
            {path: table.sliced(start, stop) for path, table in self.tables.items()},
            None if self.skips is None else self.skips[start:stop],
            [(row - start, error) for row, error in self.errors if start <= row < stop],
        )


def first_present(table):
    """Return the index of the first present tick of a path, or ``None``."""
    if table.complete:
        return 0 if len(table.present) else None
    found = np.flatnonzero(table.present)
    return int(found[0]) if found.size else None


def merge(chunks):
    """Return the chunks as one chunk, columns concatenated and not yet inferred.

    A field a chunk lacks, or a row where a path is absent, becomes NaN: a float column stays a
    ``float64`` array, any other becomes an object array that keeps its Python values.
    """
    if len(chunks) == 1:
        return chunks[0]
    sizes = [len(chunk) for chunk in chunks]
    tables = {}
    for path in dict.fromkeys(path for chunk in chunks for path in chunk.tables):
        names = dict.fromkeys(
            name for chunk in chunks if path in chunk.tables for name in chunk.tables[path].columns
        )
        present = np.concatenate(
            [
                chunk.tables[path].present if path in chunk.tables else np.zeros(size, dtype=bool)
                for chunk, size in zip(chunks, sizes)
            ]
        )
        columns = {name: _combined(_pieces(chunks, sizes, path, name)) for name in names}
        tables[path] = PathColumns(present, columns)
    return ResultChunk(
        [time for chunk in chunks for time in chunk.times],
        [duration for chunk in chunks for duration in chunk.durations],
        tables,
    )


def assemble(chunk, order, times):
    """Return the table of a merged chunk, columns in ``order``, dtypes as pandas infers them."""
    index = pd.DatetimeIndex(times, name="timestamp")
    columns = {}
    for position, (path, name) in enumerate(order):
        values = _combined(_pieces([chunk], [len(chunk)], path, name))
        series = pd.Series(values, index=index, copy=False)
        columns[position] = series.infer_objects() if values.dtype == object else series
    frame = pd.DataFrame(columns, index=index)
    names = ["module_path", "field"]
    if order:
        frame.columns = pd.MultiIndex.from_tuples(order, names=names)
    else:
        frame.columns = pd.MultiIndex.from_arrays([[], []], names=names)
    return frame


def _pieces(chunks, sizes, path, name):
    """Return ``(size, values, table)`` per chunk; values are ``None`` where the field is absent."""
    pieces = []
    for chunk, size in zip(chunks, sizes):
        table = chunk.tables.get(path)
        pieces.append((size, None if table is None else table.columns.get(name), table))
    return pieces


def _typed_column(values):
    """Return whether ``values`` is absent or a one-dimensional float, integer or flag array."""
    return values is None or (
        isinstance(values, np.ndarray) and values.ndim == 1 and values.dtype.kind in "fib"
    )


def _combined(pieces):
    """Return one column over all pieces: a typed array when it keeps its type, else objects.

    Pieces of one type that are all present concatenate unchanged. Floats with absent rows stay
    ``float64`` with NaN. Anything else, mixed types included, becomes an object array of the
    Python values with NaN for absent rows, which pandas infers like a column of row values.
    """
    arrays = [values for _, values, _ in pieces if values is not None]
    kinds = {array.dtype.kind for array in arrays if isinstance(array, np.ndarray)}
    typed = all(_typed_column(values) for _, values, _ in pieces) and len(kinds) == 1
    full = len(arrays) == len(pieces) and all(table.complete for _, _, table in pieces)
    if typed and full:
        return arrays[0] if len(arrays) == 1 else np.concatenate(arrays)
    if typed and kinds == {"f"}:
        return _filled(pieces)
    return np.concatenate([_object_piece(*piece) for piece in pieces])


def _filled(pieces):
    """Return float pieces as one ``float64`` array, NaN where a row is absent."""
    out = np.full(sum(size for size, _, _ in pieces), np.nan)
    start = 0
    for size, values, table in pieces:
        if values is not None:
            window = out[start : start + size]
            window[table.present] = values[table.present]
        start += size
    return out


def _object_piece(size, values, table):
    """Return one piece as an object array of Python values, NaN where a row is absent."""
    if values is None:
        return np.full(size, MISSING, dtype=object)
    if isinstance(values, np.ndarray) and values.ndim == 1:
        cells = values.astype(object)
    else:
        cells = np.empty(size, dtype=object)
        for row, value in enumerate(values.tolist() if isinstance(values, np.ndarray) else values):
            cells[row] = value
    if not table.complete:
        cells[~table.present] = MISSING
    return cells
