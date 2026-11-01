"""Elementwise ops: Python backend equals ``math``/builtins bit for bit, NumPy within 1e-12."""

import math
import warnings

import numpy as np
import pytest

from gemini import ops
from gemini.ops import Constant, Operators, Symbolic

SAMPLES = [-3.5, -1.0, -0.25, 0.0, 0.3, 1.0, 2.0, 7.5]
UNARY_MATH = ["exp", "expm1", "sin", "cos", "tan", "atan", "sinh", "cosh", "tanh"]
POSITIVE_MATH = ["log", "log10", "sqrt"]


class Recorder(Symbolic, Operators):
    """Symbolic operand that returns what it was asked to record."""

    def record(self, definition, operands, attributes=None):
        """Return the op name and operands."""
        return definition.name, operands


@pytest.mark.parametrize("name", UNARY_MATH)
def test_math_functions_equal_the_plain_math_call(name):
    """The Python backend returns exactly what ``math.<name>`` returns."""
    for value in SAMPLES:
        assert getattr(ops, name)(value) == getattr(math, name)(value)


@pytest.mark.parametrize("name", POSITIVE_MATH)
def test_log_and_sqrt_equal_math_on_their_domain(name):
    """On a valid operand the result is the ``math`` result."""
    for value in [0.3, 1.0, 2.0, 7.5]:
        assert getattr(ops, name)(value) == getattr(math, name)(value)


def test_inverse_trigonometry_floor_and_atan2_equal_math():
    """``asin``, ``acos``, ``atan2``, ``floor`` and ``ceil`` equal ``math``, as floats."""
    assert ops.asin(0.3) == math.asin(0.3) and ops.acos(0.3) == math.acos(0.3)
    assert ops.atan2(1.0, -2.0) == math.atan2(1.0, -2.0)
    assert ops.floor(2.7) == 2 and type(ops.floor(2.7)) is float
    assert ops.ceil(-2.7) == -2 and type(ops.ceil(2.1)) is float


def test_invalid_operands_give_inf_or_nan_silently():
    """Outside its domain an op returns what NumPy returns and neither raises nor warns."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert ops.log(0.0) == -math.inf and ops.log10(0) == -math.inf
        assert math.isnan(ops.log(-1)) and math.isnan(ops.log10(-1.0)) and math.isnan(ops.sqrt(-4))
        assert ops.exp(1000.0) == math.inf and ops.expm1(1000.0) == math.inf
        assert ops.sinh(1000.0) == math.inf and ops.cosh(-1000.0) == math.inf
        assert math.isnan(ops.asin(2.0)) and math.isnan(ops.acos(-2.0))
        assert math.isnan(ops.sin(math.inf)) and math.isnan(ops.tan(math.inf))
        assert ops.floor(math.inf) == math.inf and math.isnan(ops.ceil(math.nan))
        assert math.isnan(ops.log(np.float32(-1))) and ops.log(np.float32(0)) == -math.inf
        assert ops.log(Constant("c", 0.0, "-", "zero")) == -math.inf


def test_python_and_numpy_backends_agree_to_relative_1e12():
    """The same op on an array equals the scalar op row by row."""
    values = np.array(SAMPLES)
    for name in UNARY_MATH + POSITIVE_MATH + ["asin", "acos", "atan", "floor", "ceil"]:
        scalar = np.array([getattr(ops, name)(value) for value in SAMPLES])
        with np.errstate(all="ignore"):
            array = getattr(ops, name)(values)
        np.testing.assert_allclose(array, scalar, rtol=1e-12, equal_nan=True)


def test_abs_sign_and_comparisons_with_nan_and_inf():
    """``abs`` is the builtin; ``sign`` follows NumPy; the predicates return booleans."""
    assert ops.abs(-2.5) == 2.5 and ops.abs(-3) == 3 and ops.abs(Constant("c", -1, "-", "x")) == 1
    assert [ops.sign(value) for value in (-2.0, 0.0, 5)] == [-1.0, 0.0, 1.0]
    assert math.isnan(ops.sign(math.nan))
    assert ops.sign(np.array([-2.0, 0.0, 5.0])).tolist() == [-1.0, 0.0, 1.0]
    assert ops.isnan(math.nan) and not ops.isnan(1.0)
    assert ops.isinf(-math.inf) and not ops.isinf(1.0)
    assert ops.isfinite(1.0) and not ops.isfinite(math.nan)
    assert ops.isnan(np.array([math.nan, 1.0])).tolist() == [True, False]


def test_round_equals_python_round_on_ties_for_scalars_and_arrays():
    """``ops.round`` on an array matches Python's ``round`` item by item, not ``np.round``."""
    values = [0.5, 1.5, 2.5, 2.675, -0.5, 0.125, 1234.5678]
    for digits in (0, 1, 2):
        expected = [round(value, digits) for value in values]
        assert [ops.round(value, digits) for value in values] == expected
        assert ops.round(np.array(values), digits).tolist() == expected
    assert ops.round(np.array([[0.5, 2.5], [3.5, 2.675]]), 2).shape == (2, 2)
    assert ops.round(math.inf, 2) == math.inf


def test_maximum_minimum_and_clip_match_the_builtins():
    """On non-NaN values the ops equal ``max``/``min``; arrays act row by row."""
    pairs = [(1.0, 2.0), (2.0, 1.0), (3, 3.0), (-1.0, 0.0)]
    for left, right in pairs:
        assert ops.maximum(left, right) is max(left, right)
        assert ops.minimum(left, right) is min(left, right)
    assert ops.maximum(Constant("c", 0.001, "Pa", "floor"), 0.0) == 0.001
    assert type(ops.maximum(Constant("c", 0.001, "Pa", "floor"), 0.0)) is float
    left, right = np.array([1.0, 5.0, -2.0]), np.array([2.0, 3.0, -2.0])
    assert ops.maximum(left, right).tolist() == [max(a, b) for a, b in zip(left, right)]
    assert ops.minimum(left, right).tolist() == [min(a, b) for a, b in zip(left, right)]
    assert [ops.clip(value, 0.0, 1.0) for value in (-1.0, 0.5, 2.0)] == [0.0, 0.5, 1.0]
    assert ops.clip(np.array([-1.0, 0.5, 2.0]), 0.0, 1.0).tolist() == [0.0, 0.5, 1.0]
    assert math.isnan(ops.clip(math.nan, 0.0, 1.0))


def test_logical_ops_and_none_branches():
    """``logical_or`` and ``logical_not`` replace ``or`` and ``not``; ``where`` accepts ``None``."""
    assert ops.logical_or(False, True) is True and ops.logical_not(True) is False
    flags = np.array([True, False])
    assert ops.logical_or(flags, ~flags).tolist() == [True, True]
    assert ops.logical_not(flags).tolist() == [False, True]
    assert ops.where(False, 1.0, None) is None
    assert np.isnan(ops.where(flags, 1.0, None)[1])


def test_python_operators_mod_floordiv_and_abs():
    """``%``, ``//`` and ``abs`` on a constant act as on its float; zero divisors are silent."""
    constant = Constant("c", -7.5, "-", "x")
    assert constant % 2 == -7.5 % 2 and 20 % constant == 20 % -7.5
    assert constant // 2 == -7.5 // 2 and 20 // constant == 20 // -7.5
    assert abs(constant) == 7.5
    assert math.isnan(ops.mod(1.0, 0.0)) and ops.floordiv(1.0, 0.0) == math.inf
    assert ops.mod(np.array([5.0, -5.0]), 3).tolist() == [2.0, 1.0]


def test_symbolic_operands_record_the_new_ops():
    """An op with a symbolic operand is recorded under its own name."""
    symbolic = Recorder()
    assert ops.log(symbolic) == ("log", (symbolic,))
    assert ops.maximum(1.0, symbolic) == ("maximum", (1.0, symbolic))
    assert ops.clip(symbolic, 0, 1) == ("clip", (symbolic, 0, 1))
    assert symbolic % 2 == ("mod", (symbolic, 2)) and abs(symbolic) == ("abs", (symbolic,))
    assert 7 // symbolic == ("floordiv", (7, symbolic))


def test_maximum_minimum_propagate_nan_on_either_side_like_arrays():
    """A NaN right operand gives NaN on scalars, as the array path does."""
    nan = math.nan
    for function in (ops.maximum, ops.minimum):
        assert math.isnan(function(1.0, nan))
        assert math.isnan(function(nan, 1.0))
        assert np.isnan(function(np.array([1.0]), nan)).all()


def test_floor_and_ceil_of_scalars_are_floats_like_arrays():
    """The scalar path returns floats, as the array path does."""
    assert type(ops.floor(2.5)) is float and ops.floor(2.5) == 2.0
    assert type(ops.ceil(2.5)) is float and ops.ceil(2.5) == 3.0
    assert ops.floor(np.array([2.5])).dtype == np.float64
