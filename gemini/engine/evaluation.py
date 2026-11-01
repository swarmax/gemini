"""``Evaluation``: what an executor gives for one module over the rows of a chunk.

``result`` is the ``ModuleResult`` tree mapped to arrays of ``rows`` (children included): a
literal broadcasts, a list of values is an array of shape ``(rows, n)``, ``None`` is NaN
(``ModuleResult.row`` reads it back as ``None`` for a declared ``X | None``) and an output has
the dtype its declaration gives on the plain path. ``failed`` marks the failed rows and
``error(row)`` is the exception of that row. ``states`` are the states after a stepped call,
``stepped`` tells that the call was stepped and ``breaks`` lists ``(path, reason)`` of the
places an executor ran a module for real instead of in its own way.
"""

import dataclasses

import numpy as np

from gemini.ops import Constant
from gemini.types.results import Values

DTYPES = {"number": float, "boolean": bool, "integer": np.int64}
"""The NumPy type of an output by the JSON type of its declaration."""


class Evaluation:
    """The result of evaluating a module over ``rows`` rows."""

    def __init__(self, rows, failed, result, errors, states=None, stepped=False, breaks=()):
        """Keep the mapped ``result``, the ``failed`` mask and ``errors``, kept as ``error``.

        ``error(row)`` returns the exception of a failed row: the check's class, its exact message.
        """
        self.rows = rows
        self.failed = failed
        self.result = result
        self.states = states
        self.stepped = stepped
        self.breaks = list(breaks)
        self.error = errors

    def raise_first(self):
        """Raise the exception of the first failed row, if any."""
        if self.failed.any():
            raise self.error(int(np.flatnonzero(self.failed)[0]))


def converter(rows, traced=(), column=None):
    """Return the function that maps a value of a result tree to an array over ``rows``.

    A value of one of the ``traced`` types is mapped by ``column``; a literal broadcasts, a list
    or tuple stacks into shape ``(rows, n)`` and ``None`` is NaN.
    """

    def convert(value):
        if isinstance(value, traced):
            return column(value)
        if isinstance(value, (list, tuple)):
            items = [convert(item) for item in value]
            return np.stack(items, axis=1) if items else np.empty((rows, 0))
        if isinstance(value, Constant):
            value = value.value
        if value is None:
            return np.full(rows, np.nan)
        if isinstance(value, (bool, int, float, np.number, np.bool_)):
            return np.full(rows, value)
        if isinstance(value, np.ndarray) and not value.ndim:
            return np.full(rows, value[()])
        return value

    return convert


def typed(result, done=None):
    """Return ``result`` with the outputs in the dtype their declarations have on the plain path."""
    done = {} if done is None else done
    if id(result) in done:
        return done[id(result)]
    declarations = result.outputs._declarations
    values = {name: _cast(value, declarations.get(name)) for name, value in result.outputs.items()}
    tree = dataclasses.replace(
        result,
        outputs=Values._trusted(values, declarations),
        children={name: typed(child, done) for name, child in result.children.items()},
        call_records=tuple((name, typed(child, done)) for name, child in result.call_records),
    )
    done[id(result)] = tree
    return tree


def _cast(value, declaration):
    if declaration is None or not isinstance(value, np.ndarray):
        return value
    kind = DTYPES.get(declaration.value_type())
    if kind is None or value.dtype.kind not in "biuf":
        return value
    return value.astype(kind)
