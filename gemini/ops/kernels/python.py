"""Scalar backend: plain Python operators on floats, NumPy scalars and bools.

This is the plain-call, row-by-row path and the reference of every other backend. Operators are
applied as written, so NumPy float32 scalars keep their float32 arithmetic and promotion.

``where`` evaluates both of its branches, so an op never raises and never warns on an operand
that is invalid in the branch not selected: division by zero, a power that is infinite, complex
or overflows give ``inf`` or ``nan`` exactly as NumPy does. The valid operands give the plain
Python result.
"""

import itertools
import math
from bisect import bisect_right
from itertools import accumulate

import numpy as np
from scipy import optimize

from gemini.ops.backend import Backend, quiet

PLAIN_NUMBERS = frozenset({float, int})
DIVISIBLE = PLAIN_NUMBERS | {np.float64}


def numpy_float(function, *values):
    """Return ``function`` of ``values`` as a Python float computed the way NumPy computes it."""
    return float(quiet(function, *(float(value) for value in values)))


class PythonBackend(Backend):
    """Evaluate ops on scalars with Python operators."""

    name = "python"

    def add(self, left, right):
        """Return ``left + right``."""
        return left + right

    def sub(self, left, right):
        """Return ``left - right``."""
        return left - right

    def mul(self, left, right):
        """Return ``left * right``."""
        return left * right

    def truediv(self, left, right):
        """Return ``left / right``; a zero divisor gives ``inf`` or ``nan`` as in IEEE 754."""
        if type(left) not in DIVISIBLE or type(right) not in DIVISIBLE:
            return quiet(np.true_divide, left, right)
        if right != 0:
            return left / right
        if left == 0 or math.isnan(left):
            return math.nan
        return math.copysign(math.inf, left) * math.copysign(1.0, right)

    def pow(self, base, exponent):
        """Return ``base ** exponent``; an invalid or overflowing power gives ``inf`` or ``nan``."""
        if type(base) not in PLAIN_NUMBERS or type(exponent) not in PLAIN_NUMBERS:
            return quiet(np.power, base, exponent)
        try:
            result = base**exponent
        except (ZeroDivisionError, OverflowError):
            return numpy_float(np.power, base, exponent)
        if type(result) is complex:
            return math.nan
        return result

    def identity(self, value):
        """Return ``value`` unchanged."""
        return value

    def neg(self, value):
        """Return ``-value``."""
        return -value

    def lt(self, left, right):
        """Return ``left < right``."""
        return left < right

    def le(self, left, right):
        """Return ``left <= right``."""
        return left <= right

    def gt(self, left, right):
        """Return ``left > right``."""
        return left > right

    def ge(self, left, right):
        """Return ``left >= right``."""
        return left >= right

    def eq(self, left, right):
        """Return ``left == right``."""
        return left == right

    def ne(self, left, right):
        """Return ``left != right``."""
        return left != right

    def logical_and(self, left, right):
        """Return whether both conditions hold."""
        return bool(left) and bool(right)

    def where(self, condition, if_true, if_false):
        """Return the selected branch unchanged, ``None`` included."""
        return if_true if condition else if_false

    def check(self, condition, code):
        """Return 0 where ``condition`` holds, else the error ``code``."""
        return 0 if condition else code

    def getitem(self, value, index):
        """Return item ``index`` of a vector value."""
        return value[index]

    def mod(self, left, right):
        """Return ``left % right``; a zero divisor gives ``nan``."""
        if type(left) not in PLAIN_NUMBERS or type(right) not in PLAIN_NUMBERS:
            return quiet(np.mod, left, right)
        if right == 0:
            return math.nan
        return left % right

    def floordiv(self, left, right):
        """Return ``left // right``; a zero divisor gives ``inf`` or ``nan``."""
        if type(left) not in PLAIN_NUMBERS or type(right) not in PLAIN_NUMBERS:
            return quiet(np.floor_divide, left, right)
        if right == 0:
            return numpy_float(np.floor_divide, left, right)
        return left // right

    def abs(self, value):
        """Return the absolute value of ``value``."""
        return abs(value)

    def sign(self, value):
        """Return 1.0, -1.0 or 0.0 by the sign of ``value``; ``nan`` stays ``nan``."""
        if value > 0:
            return 1.0
        if value < 0:
            return -1.0
        if value == 0:
            return 0.0
        return value

    def round(self, value, digits):
        """Return ``value`` rounded to ``digits`` decimals, ties to even as Python does.

        NOTE(refactor): an ``np.float64`` is rounded as a ``float``, not with NumPy's own rounding.
        """
        if type(value) is np.float64:
            value = float(value)
        return round(value, digits)

    def maximum(self, left, right):
        """Return the larger value as the builtin ``max(left, right)`` does; ``nan`` propagates."""
        return right if right > left or right != right else left

    def minimum(self, left, right):
        """Return the smaller value as the builtin ``min(left, right)`` does; ``nan`` propagates."""
        return right if right < left or right != right else left

    def clip(self, value, low, high):
        """Return ``value`` limited to ``[low, high]``; ``nan`` stays ``nan``."""
        if value < low:
            return low
        if value > high:
            return high
        return value

    def isnan(self, value):
        """Return whether ``value`` is ``nan``."""
        return math.isnan(value)

    def isinf(self, value):
        """Return whether ``value`` is infinite."""
        return math.isinf(value)

    def isfinite(self, value):
        """Return whether ``value`` is finite."""
        return math.isfinite(value)

    def logical_or(self, left, right):
        """Return whether either condition holds."""
        return bool(left) or bool(right)

    def logical_not(self, value):
        """Return whether the condition does not hold."""
        return not value

    def exp(self, value):
        """Return ``e ** value``; an overflow gives ``inf``."""
        try:
            return math.exp(value)
        except (ValueError, OverflowError):
            return numpy_float(np.exp, value)

    def expm1(self, value):
        """Return ``exp(value) - 1``; an overflow gives ``inf``."""
        try:
            return math.expm1(value)
        except (ValueError, OverflowError):
            return numpy_float(np.expm1, value)

    def log(self, value):
        """Return the natural logarithm; zero gives ``-inf`` and a negative value ``nan``."""
        try:
            return math.log(value)
        except (ValueError, OverflowError):
            return numpy_float(np.log, value)

    def log10(self, value):
        """Return the base-10 logarithm; zero gives ``-inf`` and a negative value ``nan``."""
        try:
            return math.log10(value)
        except (ValueError, OverflowError):
            return numpy_float(np.log10, value)

    def sqrt(self, value):
        """Return the square root; a negative value gives ``nan``."""
        try:
            return math.sqrt(value)
        except (ValueError, OverflowError):
            return numpy_float(np.sqrt, value)

    def sin(self, value):
        """Return the sine of ``value`` in radians."""
        try:
            return math.sin(value)
        except (ValueError, OverflowError):
            return numpy_float(np.sin, value)

    def cos(self, value):
        """Return the cosine of ``value`` in radians."""
        try:
            return math.cos(value)
        except (ValueError, OverflowError):
            return numpy_float(np.cos, value)

    def tan(self, value):
        """Return the tangent of ``value`` in radians."""
        try:
            return math.tan(value)
        except (ValueError, OverflowError):
            return numpy_float(np.tan, value)

    def asin(self, value):
        """Return the arc sine in radians; ``nan`` outside ``[-1, 1]``."""
        try:
            return math.asin(value)
        except (ValueError, OverflowError):
            return numpy_float(np.arcsin, value)

    def acos(self, value):
        """Return the arc cosine in radians; ``nan`` outside ``[-1, 1]``."""
        try:
            return math.acos(value)
        except (ValueError, OverflowError):
            return numpy_float(np.arccos, value)

    def atan(self, value):
        """Return the arc tangent in radians."""
        return math.atan(value)

    def atan2(self, y, x):
        """Return the angle of the point ``(x, y)`` in radians."""
        return math.atan2(y, x)

    def sinh(self, value):
        """Return the hyperbolic sine; an overflow gives ``inf``."""
        try:
            return math.sinh(value)
        except (ValueError, OverflowError):
            return numpy_float(np.sinh, value)

    def cosh(self, value):
        """Return the hyperbolic cosine; an overflow gives ``inf``."""
        try:
            return math.cosh(value)
        except (ValueError, OverflowError):
            return numpy_float(np.cosh, value)

    def tanh(self, value):
        """Return the hyperbolic tangent."""
        return math.tanh(value)

    def floor(self, value):
        """Return the largest whole number not above ``value``, a float; ``inf``, ``nan`` stay."""
        try:
            return float(math.floor(value))
        except (ValueError, OverflowError):
            return numpy_float(np.floor, value)

    def ceil(self, value):
        """Return the smallest whole number not below ``value``, a float; ``inf``, ``nan`` stay."""
        try:
            return float(math.ceil(value))
        except (ValueError, OverflowError):
            return numpy_float(np.ceil, value)

    def sum(self, values):
        """Return the sum of a sequence."""
        return sum(values)

    def mean(self, values):
        """Return the mean of a sequence; an empty sequence gives ``nan``."""
        return self.truediv(sum(values), len(values))

    def cumsum(self, values):
        """Return the running sums of a sequence as a list."""
        return list(accumulate(values))

    def interp(self, x, xp, fp):
        """Return the linear interpolation at ``x``, with the same bits as ``numpy.interp``."""
        if x != x:
            return x
        index = bisect_right(xp, x) - 1
        if index < 0:
            return fp[0]
        if index == len(xp) - 1 or xp[index] == x:
            return fp[index]
        slope = (fp[index + 1] - fp[index]) / (xp[index + 1] - xp[index])
        result = slope * (x - xp[index]) + fp[index]
        if result != result:
            result = slope * (x - xp[index + 1]) + fp[index + 1]
        if result != result and fp[index] == fp[index + 1]:
            return fp[index]
        return result

    def brentq(self, low, high, *args, function, xtol, rtol, maxiter):
        """Return the root of ``function(x, *args)`` in ``[low, high]`` by ``scipy`` Brent.

        A bracket without a sign change, or no convergence, gives NaN instead of an error.
        ``function`` is given ``np.float64`` values with warnings silenced, so a plain division
        or power in it gives ``inf`` or ``nan`` like NumPy instead of raising.
        """
        try:
            return quiet(
                optimize.brentq,
                lambda value, *rest: function(np.float64(value), *rest),
                low,
                high,
                args,
                xtol,
                rtol,
                maxiter,
            )
        except (ValueError, RuntimeError):
            return math.nan

    def newton(self, start, *args, function, derivative, tolerance, max_iterations):
        """Return the Newton iterate that stops the loop, NaN where the iteration fails.

        The loop stops when a step is below ``tolerance`` times the current value, or at
        iteration ``max_iterations``, and returns the value before that step without a warning.
        ``function`` and ``derivative`` are given ``np.float64`` values with warnings silenced.
        """
        value = np.float64(start)
        with np.errstate(all="ignore"):
            for iteration in itertools.count():
                following = value - function(value, *args) / derivative(value, *args)
                if abs(following - value) < tolerance * value or iteration >= max_iterations:
                    return float(value) if math.isfinite(value) else math.nan
                value = following
