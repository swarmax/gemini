"""Root finding as ops: ``brentq`` and ``newton``, evaluated on floats, arrays and in a graph.

A solver replaces a call to ``scipy.optimize.brentq`` or a handwritten Newton loop inside physics.
The function to solve is passed to the op, which calls it later with concrete values: on the
Python backend with floats, on the NumPy backend with arrays of the rows still iterating, each
row stopping by its own rule. In a trace the solver records one ``solver`` node whose operands are
the bounds (or the start) and ``args``, and whose attributes hold the function and the settings.

**The function may not close over traced values.** It must be a module-level function, or a
nested one that captures only plain constants, and it is written with ops. Everything that varies
goes through ``args``, which become node operands:

    def _saturation_residual(point, vapour_pressure):
        return saturation_pressure(point) - vapour_pressure

    ops.brentq(_saturation_residual, low, high, args=(vapour_pressure,), xtol=1e-9)

A ``lambda point: saturation_pressure(point) - vapour_pressure`` that captures a traced
``vapour_pressure`` cannot be called by a graph and is wrong. Bounds, start and ``args`` may be
floats, arrays or traced values.

A solve that fails (no sign change of the bracket, no convergence, a non-finite iterate) gives NaN
instead of raising, so that an unselected branch of ``where`` never raises; follow the solver with
a ``where`` and a ``check`` to give the failure its error. The Python backend is exactly
``scipy.optimize.brentq`` and the handwritten Newton loop; the NumPy backend repeats the same
iterations on all rows with a mask (see ``gemini.ops.kernels.solvers``).
"""

from gemini.errors import ValidationError
from gemini.ops.dispatch import dispatch
from gemini.ops.elementwise import logical_or
from gemini.ops.logic import eq, ge, where
from gemini.ops.math import truediv
from gemini.ops.registry import register

BRENT_RTOL = 8.881784197001252e-16
"""``scipy.optimize.brentq``'s default and minimum relative tolerance, four machine epsilons."""

register("brentq", "solver", 2)
register("newton", "solver", 1)


def brentq(function, low, high, args=(), xtol=2e-12, rtol=BRENT_RTOL, maxiter=100):
    """Return the root of ``function(x, *args)`` between ``low`` and ``high`` by Brent's method.

    ``function`` is a module-level function written with ops (see the module docstring); every
    value it needs besides ``x`` is in ``args``. The result is NaN where the bracket has no sign
    change or the method does not converge in ``maxiter`` steps. Convergence follows
    ``scipy.optimize.brentq``: ``xtol + rtol * abs(x)``.
    """
    if xtol <= 0 or rtol < BRENT_RTOL or maxiter < 1:
        raise ValidationError(
            f"ops.brentq: xtol = {xtol}, rtol = {rtol}, maxiter = {maxiter}; expected xtol > 0, "
            f"rtol >= {BRENT_RTOL} and maxiter >= 1",
            code="invalid_design",
        )
    attributes = {"function": function, "xtol": xtol, "rtol": rtol, "maxiter": maxiter}
    return dispatch("brentq", low, high, *args, attributes=attributes)


def newton(function, start, derivative, args=(), tolerance=1e-6, max_iterations=100):
    """Return the Newton iterate of ``function(x, *args)`` from ``start``, NaN if it fails.

    ``function`` and ``derivative`` are module-level functions written with ops that take
    ``(x, *args)`` (see the module docstring). A row stops when a step is smaller than
    ``tolerance`` times the current value, or at iteration ``max_iterations``, and keeps the value
    before that step without a warning. The result is NaN when a step divides by zero, overflows
    or the iterate is not finite.
    """
    attributes = {
        "function": function,
        "derivative": derivative,
        "tolerance": tolerance,
        "max_iterations": max_iterations,
    }
    return dispatch("newton", start, *args, attributes=attributes)


def wegstein(current, image, previous, previous_image):
    """Return the next iterate of one field by Wegstein's method, per element.

    Wegstein's accelerated successive substitution (Wegstein 1958, "Accelerating convergence of
    iterative processes", Communications of the ACM 1(6), 9-13) is the classic recycle-convergence
    method of sequential-modular flowsheet simulators: with ``g = image`` and the secant slope
    ``s`` between the last two iterates, ``x_next = q x + (1 - q) g`` with ``q = s / (s - 1)`` for
    ``s < 1`` and plain substitution (``q = 0``) otherwise. It is exact in one accelerated step on
    a linear piece of the pass, so loops of effectiveness heat exchangers and consumers with
    capped duties close in a few passes. An iterate without history has ``previous = current``
    and takes the image, as an iterate that stands still does.

    It is written with ops, so it runs on floats, on arrays (each row its own step, as alone) and
    in a trace. A slope that divides by zero is not selected and raises nothing.
    """
    slope = truediv(image - previous_image, current - previous)
    weight = truediv(slope, slope - 1)
    accelerated = weight * current + (1 - weight) * image
    substitute = logical_or(eq(current, previous), ge(slope, 1))
    return where(substitute, image, accelerated)
