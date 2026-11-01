"""The eager executor: ``forward`` on arrays over the whole chunk, row by row only when it must.

A module without state, loop, constraint or pre-hook is called once on the arrays of the chunk
(the NumPy kernels do the rows at once). Any other module, a run on the Python backend and a
precision other than float64 call the module for real on each row (``gemini.engine.rows``), and so
does an array call that raised: the call of each row then gives the exception of its own row, so
the rows that work are never lost to one that fails.
"""

from typing import NamedTuple

import numpy as np

from gemini import runtime
from gemini.engine.evaluation import Evaluation, converter, typed
from gemini.engine.executor import EAGER, Executor, register_executor
from gemini.engine.rows import applied, inlet_feeds, run_rows, stacked
from gemini.errors import RunError
from gemini.ops import kernels
from gemini.ops.failures import marking, merge
from gemini.types.flows import STREAM_FIELDS, Stream


class Call(NamedTuple):
    """A module with the inlet streams and inputs of the selected rows."""

    module: object
    streams: dict
    inputs: dict
    stepped: bool


class EagerExecutor(Executor):
    """Evaluate a module as a direct call does, over arrays when it can."""

    def prepare(self, module, streams, inputs, stepped):
        """Keep the call; nothing is traced or compiled."""
        return Call(module, streams, inputs, stepped)

    def evaluate(self, prepared, rows, context):
        """Return the evaluation over ``rows``: one array call, else one call per row.

        A row that fails a check is a failed row of the array call. The array call falls back to
        the rows only when it raised something that no row can be blamed for, whatever its class: a
        module written for one row (``if`` on an array), a shape or a validation error of the whole
        call. The row call is the reference there, and the reason is kept in ``breaks``.
        """
        if _by_rows(prepared.module):
            return self._rows(prepared, rows, context)
        try:
            return self._arrays(prepared, rows)
        except Exception as error:
            reason = f"array call raised {type(error).__name__}: {error}"
        evaluation = self._rows(prepared, rows, context)
        evaluation.breaks.append((prepared.module.path, reason))
        return evaluation

    def _arrays(self, call, rows):
        """Return the evaluation of one array call; rows an inline check refused are left out."""
        try:
            return self._once(call, rows)
        except Exception as error:
            refused = getattr(error, "failures", None)
            if refused is None or refused.mask.all():
                raise
        keep = ~refused.mask
        inner = self._arrays(_restricted(call, keep), int(keep.sum()))
        return _scattered(inner, keep, refused)

    def _once(self, call, rows):
        with marking() as marked, applied(call.module, call.inputs):
            result = call.module(call.streams)
        failures = _failures(result, marked)
        tree = typed(result.mapped(converter(rows)))
        if failures is None:
            return Evaluation(rows, np.zeros(rows, dtype=bool), tree, _no_error)
        return Evaluation(rows, failures.mask, tree, failures.error)

    def _rows(self, call, rows, context):
        module = call.module
        stepped = call.stepped and any(member.stateful for member in module.modules())
        fluids = {port: stream.fluid for port, stream in call.streams.items()}
        feeds = inlet_feeds(call.streams) | call.inputs
        results, errors, states = run_rows(module, fluids, feeds, rows, context, stepped)
        failed = np.ones(rows, dtype=bool)
        failed[list(results)] = False
        result = stacked(results, rows)
        tree = None if result is None else typed(result)
        return Evaluation(rows, failed, tree, errors.__getitem__, states, stepped)


def _failures(result, marked):
    """Return the failures that reach the arrays of ``result`` or were required, else ``None``."""
    found = []

    def visit(value):
        found.append(value)
        return value

    result.mapped(visit)
    return merge([*found, *marked.required])


def _restricted(call, keep):
    """Return ``call`` on the rows of ``keep`` only."""
    streams = {port: _rows_of(stream, keep) for port, stream in call.streams.items()}
    inputs = {name: _rows_of(value, keep) for name, value in call.inputs.items()}
    return Call(call.module, streams, inputs, call.stepped)


def _rows_of(value, keep):
    if isinstance(value, Stream):
        fields = (_rows_of(getattr(value, name), keep) for name in STREAM_FIELDS)
        return Stream._trusted(*fields, value.fluid)
    return value[keep] if np.ndim(value) else value


def _scattered(inner, keep, refused):
    """Return the evaluation over all rows from ``inner``, the one over the rows of ``keep``."""
    rows = len(keep)
    failed = refused.mask.copy()
    failed[keep] = inner.failed
    positions = np.cumsum(keep) - 1

    def error(row):
        return inner.error(int(positions[row])) if keep[row] else refused.error(row)

    def spread(value):
        if not np.ndim(value) or len(value) != inner.rows:
            return value
        fill = np.nan if value.dtype.kind == "f" else 0
        full = np.full((rows, *value.shape[1:]), fill, dtype=value.dtype)
        full[keep] = value
        return full

    return Evaluation(rows, failed, inner.result.mapped(spread), error)


def _by_rows(module):
    """Return whether ``module`` must be called row by row."""
    if kernels.forced_name() == "python" or runtime.get_precision() != "float64":
        return True
    return any(
        member.stateful or member._iterates() or member._pre_hooks for member in module.modules()
    )


def _no_error(row):
    raise RunError(f"row {row}: did not fail; expected a failed row", code="step")


register_executor(EAGER, lambda plant: EagerExecutor())
