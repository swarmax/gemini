"""Call a module for real, row by row, and stack the results of the rows into arrays.

``run_rows`` calls ``module(streams)`` for each row (``module.step(state, dt, streams)`` for a
stepped module, so the state tree, the ``_Step`` record and "called twice" stay in
``Module.step``, the one implementation). ``feeds`` maps ``<port>.<field>`` to the column of an
inlet field and a dotted control or boundary path to its column; the controls and boundaries are
validated and put back after the call, because persisting inputs is the caller's business. A row
that raises is a failed row with that exception, and the states carry over it unchanged. The
rows are real ``ModuleResult`` trees, so children and the combinations of a plant are exact;
``stacked`` joins them into one tree of arrays.
"""

from contextlib import contextmanager

import numpy as np

from gemini import runtime
from gemini.types.flows import STREAM_FIELDS, Stream

_ABSENT = object()


def row_item(value, row):
    """Return row ``row`` of a column as a plain Python value; a scalar holds for every row."""
    array = np.asarray(value)
    return array[row].item() if array.ndim else array.item()


def stack_column(values):
    """Return the values of one position over the rows as an array; ``None`` is NaN."""
    return np.array([np.nan if value is None else value for value in values])


def row_streams(fluids, value):
    """Return the inlet streams of one row: ``value(port, field)`` for each field of each port."""
    return {
        port: Stream._si(**{field: value(port, field) for field in STREAM_FIELDS}, fluid=fluid)
        for port, fluid in fluids.items()
    }


def inlet_feeds(streams):
    """Return the columns of the fields of ``streams`` by ``<port>.<field>``."""
    return {
        f"{port}.{field}": np.asarray(getattr(stream, field))
        for port, stream in streams.items()
        for field in STREAM_FIELDS
    }


def run_rows(module, fluids, feeds, rows, context, stepped):
    """Call ``module`` on every row; return results, errors and states.

    ``fluids`` maps the inlets to their fluids. ``results`` and ``errors`` map the row index to
    the ``ModuleResult`` or the exception of that row. ``context`` may hold ``dt`` (seconds, one
    number or one per row) and ``states`` (the state tree a stepped call starts from, ``None``
    for the initial states); the returned states are those after the last row that did not fail.
    """
    state = context.get("states")
    feeds = {name: _column(value) for name, value in feeds.items()}
    steps = np.broadcast_to(np.asarray(context.get("dt", np.nan), dtype=float), (rows,))
    results, errors = {}, {}
    for row in range(rows):
        try:
            result, state = _call_row(module, fluids, feeds, row, float(steps[row]), state, stepped)
        except Exception as error:
            errors[row] = error
            continue
        results[row] = result
    return results, errors, state if stepped else None


def _column(value):
    """Return a column as a list of plain Python values, a scalar as its one value."""
    array = np.asarray(value)
    return array.tolist() if array.ndim else array.item()


def _at(column, row):
    """Return row ``row`` of a column made by ``_column``."""
    return column[row] if type(column) is list else column


def _call_row(module, fluids, feeds, row, dt, state, stepped):
    """Return the result of one row and the states after it; ``feeds`` are ``_column`` values."""
    streams = row_streams(fluids, lambda port, field: _at(feeds[f"{port}.{field}"], row))
    fields = {f"{port}.{field}" for port in fluids for field in STREAM_FIELDS}
    inputs = {name: _at(value, row) for name, value in feeds.items() if name not in fields}
    with runtime.settings(backend=None), applied(module, inputs):
        if not stepped:
            return module(streams), state
        next_state, result = module.step(state, dt, streams)
        return result, next_state


@contextmanager
def applied(module, inputs):
    """Hold ``inputs`` (controls and boundaries by dotted path) on their owners for one call.

    A value is validated as ``Module._set_inputs`` does, each item of a column of rows; NaN is the
    ``None`` of a declared ``X | None``. The previous values are put back afterwards.
    """
    declarations = module.inputs()
    saved = []
    try:
        for path, value in inputs.items():
            declaration = declarations[path]
            store = declaration.owner._input_values
            saved.append((store, declaration.name, store.get(declaration.name, _ABSENT)))
            store[declaration.name] = _validated(declaration, value)
        yield
    finally:
        for store, name, previous in reversed(saved):
            if previous is _ABSENT:
                store.pop(name, None)
            else:
                store[name] = previous


def _validated(declaration, value):
    """Return ``value`` validated by ``declaration``; a column stays a column.

    A numeric column is validated at each distinct value once: the rule has no other input.
    """
    if np.ndim(value):
        array = np.asarray(value)
        for item in (np.unique(array) if array.dtype.kind in "biuf" else array).tolist():
            _validated(declaration, item)
        return value
    if declaration.accepts_none() and value != value:
        value = None
    return declaration.validate(value)


def stacked(results, rows):
    """Return the results of the ok rows as one tree of arrays of ``rows``, or ``None``.

    The tree has the structure of the first ok row; a failed row is NaN. Every row has the
    structure of the first: the same children, outputs and streams.
    """
    if not results:
        return None
    first = next(iter(results.values()))
    flat = {row: _flatten(result) for row, result in results.items()}
    absent = [_missing(value) for value in flat[next(iter(flat))]]
    table = [flat.get(row, absent) for row in range(rows)]
    columns = iter(stack_column(column) for column in zip(*table))
    return first.mapped(lambda _: next(columns))


def _missing(value):
    """Return what a failed row holds in a column of ``value``: NaN, or a list of them."""
    return [np.nan] * len(value) if isinstance(value, (list, tuple)) else np.nan


def _flatten(result):
    """Return every value of a result tree in the order ``ModuleResult.mapped`` visits them."""
    values = []

    def visit(value):
        values.append(value)
        return value

    result.mapped(visit)
    return values
