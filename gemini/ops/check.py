"""``check``: validity checks that raise a ``gm.errors`` class, or yield per-row error codes.

``check(condition, error, message, **values)`` replaces ``if not condition: raise error(...)``.
``message`` is a ``str.format`` template filled with ``values`` of the failing row, so
``check(flow >= 0, PhysicsError, "{path}: flow = {flow} m3/s", path=self.path, flow=flow)``
raises exactly the message of the former f-string. On concrete values it raises at once, for
the first failing row of an array. In a trace it records a ``check`` node. ``values`` only fill
the message. The error code guards the results of the ``@ops.physics`` function that recorded the
check (all of them), so it travels with them through the arithmetic; ``where`` keeps only the codes
of the selected branch, and only an error that reaches a graph output is raised, after the run. A
check recorded outside any physics function (inline in ``forward``) raises at once when eager, so
the tracer guards every graph output with it.

In an eager scope (``gemini.ops.scope``) a failing check on concrete scalars raises its real error
marked as coming from a check; ``ops.physics`` turns that into a ``Failed`` value at the function's
boundary, so ``where`` can drop it. A check whose condition or named values are already ``Failed``
does nothing: the earlier failure is the one the value carries. A failing check on an eager array
raises at once, for the first failing row, unless the caller asked for ``marking`` (the eager
executor does): inside a physics function it then marks the failing rows of the function's results
(``gemini.ops.failures``), outside one it raises with the failures of all its rows in
``error.failures``. A row that already failed is not checked again.
"""

import numpy as np

from gemini.errors import PhysicsError
from gemini.ops.dispatch import Constant, Symbolic
from gemini.ops.elementwise import isnan, logical_not, logical_or
from gemini.ops.failed import mark
from gemini.ops.failures import (
    Failures,
    current_frame,
    is_marking,
    merge,
    stripped,
)
from gemini.ops.registry import get, register

register("check", "check", 1)


def check(condition, error, message, code=None, **values):
    """Raise ``error(message.format(**values), code=code)`` where ``condition`` fails.

    ``code`` is the ``gm.errors.CODES`` entry of the error, the default of its class when ``None``.
    In a trace the check is recorded instead.
    """
    traced = condition if isinstance(condition, Symbolic) else _first_traced(values)
    if traced is not None:
        attributes = {"error": error, "message": message, "values": values, "code": code}
        traced.record(get("check"), (condition,), attributes)
        return
    if condition is True:
        return
    if not isinstance(condition, np.ndarray):
        if condition:
            return
        concrete = {name: _concrete(value) for name, value in values.items()}
        raise mark(failure(error, message, concrete, 0, code))
    failing = _failing_rows(condition, values)
    if not failing.any():
        return
    concrete = {name: _concrete(value) for name, value in values.items()}

    def build(row):
        return failure(error, message, concrete, row, code)

    if not is_marking():
        raise build(int(np.flatnonzero(failing)[0]))
    failures = Failures.at(failing, build)
    frame = current_frame()
    if frame is not None:
        frame.add(failures)
        return
    raised = build(int(np.flatnonzero(failing)[0]))
    raised.failures = failures
    raise raised


def _failing_rows(condition, values):
    """Return per row whether ``condition`` fails; a row that already failed does not count."""
    failing = np.logical_not(stripped(condition))
    if failing.ndim > 1:
        failing = failing.reshape(len(failing), -1).any(axis=1)
    if not failing.any():
        return failing
    earlier = merge((condition, *values.values()))
    return failing if earlier is None else failing & ~earlier.mask


def check_numbers(function, **values):
    """Raise ``PhysicsError`` where a named value of ``function`` is NaN.

    A NaN input would otherwise return NaN as if it were a valid result. One check per value, in
    the order given, with the message ``"<function>: <name> = nan; expected a number"``.
    """
    for name, value in values.items():
        check(
            logical_not(isnan(value)),
            PhysicsError,
            "{function}: {name} = nan; expected a number",
            function=function,
            name=name,
        )


def failure(error, message, values, row, code=None):
    """Return the ``error`` of one failing ``row``, its message filled from ``values``.

    A ``path`` among the values, the module path the message names, is also the ``path`` of the
    error, so a failed row is recorded under the module that raised.
    """
    filled = {name: _row_value(value, row) for name, value in values.items()}
    where = filled.get("path")
    if isinstance(where, str) and where:
        return error(message.format(**filled), code=code, path=where)
    return error(message.format(**filled), code=code)


def _first_traced(values):
    for value in values.values():
        if isinstance(value, Symbolic):
            return value
    return None


def _concrete(value):
    return value.value if isinstance(value, Constant) else value


def _row_value(value, row):
    if isinstance(value, np.ndarray) and value.ndim:
        return value[row].item()
    return value


def any_nan(*values):
    """Return whether any of ``values`` is NaN, per row.

    A NaN result from a NaN input is passed through; a NaN result from finite inputs is a negative
    base of a fractional power, which was a complex number in Python.
    """
    missing = isnan(values[0])
    for value in values[1:]:
        missing = logical_or(missing, isnan(value))
    return missing
