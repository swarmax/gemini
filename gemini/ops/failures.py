"""``FailedRows``: the array counterpart of ``Failed``, one failure per failing row.

A ``check`` that fails on some rows of an array, inside an ``@ops.physics`` function, cannot raise
if ``where`` is to drop the rows of a branch it does not select. When the caller asked for it
(``marking``, which the eager executor does), the check instead records ``Failures``: for each
row the number of its first failing check and, for each such check, how to build that row's
exception. The function's results leave it as ``FailedRows``, an ``ndarray`` that carries the
``Failures`` through ``gemini.ops`` and plain NumPy arithmetic (the lowest check number of the
operands wins, as in ``Failed.record``). ``where`` keeps the failures of the selected branch of
each row. A value without a failing row is never a ``FailedRows``, so the clean path has no
subclass. An array has the rows on its first axis; any other array carries nothing.

A check outside every physics function (inline in ``forward``) raises, with the failures of all
its rows in ``error.failures`` so that a caller can leave those rows out and run the others.
"""

import dataclasses
from contextlib import contextmanager
from contextvars import ContextVar
from itertools import count

import numpy as np

NONE = np.iinfo(np.int64).max
"""The number of the failing check of a row that did not fail."""

_creation = count()
_marking = ContextVar("gemini_marking", default=None)
_frame = ContextVar("gemini_frame", default=None)
_NUMBERS = (float, int, bool, np.floating, np.integer, np.bool_)


def next_order():
    """Return the number of the next failing check: the lower one ran first."""
    return next(_creation)


class Failures:
    """The first failing check of each row: ``order`` is its number, ``NONE`` where none failed."""

    __slots__ = ("order", "sources")

    def __init__(self, order, sources):
        """Keep ``order`` (an integer array over rows) and ``sources``, a builder per number."""
        self.order = order
        self.sources = sources

    @classmethod
    def at(cls, failing, build):
        """Return the failures of a new check that failed at the rows of ``failing``.

        ``build(row)`` returns the exception of a row.
        """
        number = next_order()
        return cls(np.where(failing, number, NONE), {number: build})

    @property
    def mask(self):
        """Return which rows have failed."""
        return self.order != NONE

    def error(self, row):
        """Return the exception of a failed ``row``."""
        return self.sources[int(self.order[row])](row)

    def merged(self, other):
        """Return the failures of both: the lower check number of each row."""
        if other is None or other is self:
            return self
        take = other.order < self.order
        return Failures(np.where(take, other.order, self.order), self.sources | other.sources)

    def only(self, selected):
        """Return these failures at the rows of ``selected``, no failure elsewhere."""
        return Failures(np.where(selected, self.order, NONE), self.sources)


class FailedRows(np.ndarray):
    """An array over rows some of which failed; ``failures`` says which and why."""

    failures = None

    def __array_finalize__(self, obj):
        """Keep the failures of the array this one was made from while it has the same rows."""
        failures = getattr(obj, "failures", None)
        if failures is not None and self.shape[:1] == failures.order.shape:
            self.failures = failures

    def __array_ufunc__(self, ufunc, method, *inputs, out=None, **kwargs):
        """Apply the ufunc to the plain arrays and give the result the failures of the inputs."""
        if out is not None:
            kwargs["out"] = tuple(stripped(item) for item in out)
        result = getattr(ufunc, method)(*(stripped(item) for item in inputs), **kwargs)
        failures = merge(inputs)
        if isinstance(result, tuple):
            return tuple(carried(item, failures) for item in result)
        return carried(result, failures)

    def __array_function__(self, func, types, args, kwargs):
        """Apply a NumPy function to the plain arrays and carry the failures of its arguments."""
        failures = merge((*args, *kwargs.values()))
        if func is np.where and len(args) == 3:
            failures = selection(*args)
        result = func(*stripped(args), **stripped(kwargs))
        return carried(result, failures)


def failures_of(value):
    """Return the ``Failures`` of ``value``, a list or tuple of values, or ``None``."""
    if type(value) is FailedRows:
        return value.failures
    if isinstance(value, (list, tuple)):
        return merge(value)
    return None


def merge(values):
    """Return the failures of all of ``values`` together, ``None`` if there are none."""
    found = None
    for value in values:
        failures = failures_of(value)
        if failures is not None:
            found = failures if found is None else found.merged(failures)
    return found


def stripped(value):
    """Return ``value`` without ``FailedRows``: lists, tuples and dicts of values too."""
    kind = type(value)
    if kind is FailedRows:
        return value.view(np.ndarray)
    if kind is list or kind is tuple:
        return kind(stripped(item) for item in value)
    if kind is dict:
        return {name: stripped(item) for name, item in value.items()}
    return value


def carried(result, failures):
    """Return ``result`` as ``FailedRows`` when it holds the rows of ``failures`` and one failed."""
    if failures is None or not isinstance(result, np.ndarray) or not result.ndim:
        return result
    if result.shape[0] != failures.order.shape[0] or not failures.mask.any():
        return result
    rows = result.view(FailedRows)
    rows.failures = failures
    return rows


def selection(condition, if_true, if_false):
    """Return the failures ``where`` keeps: the condition's, and each branch's where selected."""
    failures = failures_of(condition)
    for branch, chosen in ((if_true, True), (if_false, False)):
        found = failures_of(branch)
        if found is not None:
            failures = _joined(failures, found.only(_selected(stripped(condition), chosen, found)))
    return failures


def _joined(failures, other):
    return other if failures is None else failures.merged(other)


def _selected(condition, chosen, failures):
    """Return per row whether ``condition`` selects the branch ``chosen`` (any element)."""
    rows = failures.order.shape[0]
    flags = np.asarray(condition, dtype=bool)
    flags = np.broadcast_to(flags, (rows, 1)) if not flags.ndim else flags.reshape(rows, -1)
    return flags.any(axis=1) if chosen else ~flags.all(axis=1)


def applied(name, method, values, attributes):
    """Run op ``name`` of ``method`` on ``values`` that hold failures; carry them to the result."""
    failures = selection(*values) if name == "where" else merge(values)
    result = method(*stripped(values), **(attributes or {}))
    return carried(result, failures)


def attached(value, failures):
    """Return the result of a physics function with ``failures`` on every row it holds.

    A number holds every row, so it becomes an array; a list, tuple, dict or dataclass keeps its
    structure; ``None`` becomes NaN; anything else holds no rows.
    """
    kind = type(value)
    rows = failures.order.shape
    if isinstance(value, np.ndarray):
        return carried(stripped(value), _joined(failures, failures_of(value)))
    if isinstance(value, _NUMBERS) or value is None:
        return carried(np.full(rows, np.nan if value is None else value), failures)
    if kind is list or kind is tuple:
        return kind(attached(item, failures) for item in value)
    if kind is dict:
        return {name: attached(item, failures) for name, item in value.items()}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        changes = {
            field.name: attached(getattr(value, field.name), failures)
            for field in dataclasses.fields(value)
        }
        return dataclasses.replace(value, **changes)
    return value


class Marking:
    """What a marking run collects: the failures of results that were required."""

    def __init__(self):
        """Start with nothing required."""
        self.required = []


@contextmanager
def marking():
    """Make failing array checks of physics functions mark rows instead of raising.

    A ``with`` block that gives the ``Marking`` of the run.
    """
    token = _marking.set(Marking())
    try:
        yield _marking.get()
    finally:
        _marking.reset(token)


def is_marking():
    """Return whether failing array checks mark rows."""
    return _marking.get() is not None


def require(value):
    """Keep the failures of a required array so the marking run fails those rows."""
    failures = failures_of(value)
    if failures is not None:
        _marking.get().required.append(failures)


class Frame:
    """The checks that failed in one physics function; its results receive them."""

    __slots__ = ("failures", "_token")

    def __init__(self):
        """Start with no failure."""
        self.failures = None

    def __enter__(self):
        """Make this the frame that array checks record in."""
        self._token = _frame.set(self)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Leave the frame."""
        _frame.reset(self._token)

    def add(self, failures):
        """Record the failures of one check."""
        self.failures = failures if self.failures is None else self.failures.merged(failures)

    def result(self, value):
        """Return ``value`` carrying the failures of the function."""
        return value if self.failures is None else attached(value, self.failures)


def current_frame():
    """Return the frame of the innermost physics function, ``None`` outside every one."""
    return _frame.get()
