"""Array backend: NumPy ufuncs over whole time series, with floating-point warnings silenced.

Both branches of ``where`` are evaluated on every row, so the branch that is not selected may
divide by zero or overflow; those warnings are silenced here and never reach the user. A ``None``
branch of ``where`` becomes NaN. Vector
values (a parameter of shape ``(n,)``) are indexed on their last axis, which leaves room for a
leading scenario axis.
"""

import numpy as np

from gemini.ops.backend import Backend, quiet
from gemini.ops.kernels.solvers import brent_roots, newton_roots


class NumpyBackend(Backend):
    """Evaluate ops on NumPy arrays and scalars."""

    name = "numpy"

    def add(self, left, right):
        """Return ``left + right``."""
        return quiet(np.add, left, right)

    def sub(self, left, right):
        """Return ``left - right``."""
        return quiet(np.subtract, left, right)

    def mul(self, left, right):
        """Return ``left * right``."""
        return quiet(np.multiply, left, right)

    def truediv(self, left, right):
        """Return ``left / right``; a zero divisor gives ``inf`` or ``nan`` silently."""
        return quiet(np.true_divide, left, right)

    def pow(self, base, exponent):
        """Return ``base ** exponent``."""
        return quiet(np.power, base, exponent)

    def identity(self, value):
        """Return ``value`` unchanged."""
        return value

    def neg(self, value):
        """Return ``-value``."""
        return np.negative(value)

    def lt(self, left, right):
        """Return ``left < right`` per row."""
        return np.less(left, right)

    def le(self, left, right):
        """Return ``left <= right`` per row."""
        return np.less_equal(left, right)

    def gt(self, left, right):
        """Return ``left > right`` per row."""
        return np.greater(left, right)

    def ge(self, left, right):
        """Return ``left >= right`` per row."""
        return np.greater_equal(left, right)

    def eq(self, left, right):
        """Return ``left == right`` per row."""
        return np.equal(left, right)

    def ne(self, left, right):
        """Return ``left != right`` per row."""
        return np.not_equal(left, right)

    def logical_and(self, left, right):
        """Return whether both conditions hold, per row."""
        return np.logical_and(left, right)

    def where(self, condition, if_true, if_false):
        """Select per row; a ``None`` branch becomes NaN, as an array cannot hold ``None``."""
        if if_true is None:
            if_true = np.nan
        if if_false is None:
            if_false = np.nan
        return np.where(condition, if_true, if_false)

    def check(self, condition, code):
        """Return 0 on rows where ``condition`` holds, else the error ``code``."""
        return np.where(condition, 0, code)

    def getitem(self, value, index):
        """Return item ``index`` of the last axis of a vector value."""
        return np.asarray(value)[..., index]

    def mod(self, left, right):
        """Return ``left % right``; a zero divisor gives ``nan``."""
        return quiet(np.mod, left, right)

    def floordiv(self, left, right):
        """Return ``left // right``; a zero divisor gives ``inf`` or ``nan``."""
        return quiet(np.floor_divide, left, right)

    def abs(self, value):
        """Return the absolute value per row."""
        return np.absolute(value)

    def sign(self, value):
        """Return 1, -1 or 0 per row; ``nan`` stays ``nan``."""
        return np.sign(value)

    def round(self, value, digits):
        """Return every item rounded to ``digits`` decimals by Python's own ``round``.

        NOTE(refactor): ``numpy.round`` rounds ties differently from Python's ``round``, so every
        item goes through Python's own rounding to give the same values as the scalar path.
        """
        array = np.asarray(value, dtype=float)
        return np.array([round(item, digits) for item in array.ravel().tolist()]).reshape(
            array.shape
        )

    def maximum(self, left, right):
        """Return the larger value per row; ``nan`` propagates."""
        return np.maximum(left, right)

    def minimum(self, left, right):
        """Return the smaller value per row; ``nan`` propagates."""
        return np.minimum(left, right)

    def clip(self, value, low, high):
        """Return ``value`` limited to ``[low, high]`` per row."""
        return np.minimum(np.maximum(value, low), high)

    def isnan(self, value):
        """Return whether each value is ``nan``."""
        return np.isnan(value)

    def isinf(self, value):
        """Return whether each value is infinite."""
        return np.isinf(value)

    def isfinite(self, value):
        """Return whether each value is finite."""
        return np.isfinite(value)

    def logical_or(self, left, right):
        """Return whether either condition holds, per row."""
        return np.logical_or(left, right)

    def logical_not(self, value):
        """Return whether the condition does not hold, per row."""
        return np.logical_not(value)

    def exp(self, value):
        """Return ``e ** value``; an overflow gives ``inf``."""
        return quiet(np.exp, value)

    def expm1(self, value):
        """Return ``exp(value) - 1``."""
        return quiet(np.expm1, value)

    def log(self, value):
        """Return the natural logarithm; zero gives ``-inf`` and a negative value ``nan``."""
        return quiet(np.log, value)

    def log10(self, value):
        """Return the base-10 logarithm; zero gives ``-inf`` and a negative value ``nan``."""
        return quiet(np.log10, value)

    def sqrt(self, value):
        """Return the square root; a negative value gives ``nan``."""
        return quiet(np.sqrt, value)

    def sin(self, value):
        """Return the sine in radians."""
        return quiet(np.sin, value)

    def cos(self, value):
        """Return the cosine in radians."""
        return quiet(np.cos, value)

    def tan(self, value):
        """Return the tangent in radians."""
        return quiet(np.tan, value)

    def asin(self, value):
        """Return the arc sine in radians; ``nan`` outside ``[-1, 1]``."""
        return quiet(np.arcsin, value)

    def acos(self, value):
        """Return the arc cosine in radians; ``nan`` outside ``[-1, 1]``."""
        return quiet(np.arccos, value)

    def atan(self, value):
        """Return the arc tangent in radians."""
        return np.arctan(value)

    def atan2(self, y, x):
        """Return the angle of the point ``(x, y)`` in radians."""
        return np.arctan2(y, x)

    def sinh(self, value):
        """Return the hyperbolic sine."""
        return quiet(np.sinh, value)

    def cosh(self, value):
        """Return the hyperbolic cosine."""
        return quiet(np.cosh, value)

    def tanh(self, value):
        """Return the hyperbolic tangent."""
        return np.tanh(value)

    def floor(self, value):
        """Return the largest integer not above each value, as floats."""
        return np.floor(value)

    def ceil(self, value):
        """Return the smallest integer not below each value, as floats."""
        return np.ceil(value)

    def sum(self, values):
        """Return the sum over the last axis."""
        return quiet(np.sum, values, -1)

    def mean(self, values):
        """Return the mean over the last axis."""
        return quiet(np.mean, values, -1)

    def cumsum(self, values):
        """Return the running sums over the last axis."""
        return quiet(np.cumsum, values, -1)

    def interp(self, x, xp, fp):
        """Return the linear interpolation of ``(xp, fp)`` at ``x``."""
        return np.interp(x, xp, fp)

    def brentq(self, low, high, *args, function, xtol, rtol, maxiter):
        """Return the root of ``function(x, *args)`` in ``[low, high]`` per row, NaN if none."""
        return quiet(brent_roots, function, low, high, args, xtol, rtol, maxiter)

    def newton(self, start, *args, function, derivative, tolerance, max_iterations):
        """Return the Newton iterate of each row, NaN where the iteration fails."""
        return quiet(newton_roots, function, derivative, start, args, tolerance, max_iterations)
