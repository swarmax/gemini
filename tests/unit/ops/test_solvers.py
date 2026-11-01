"""``ops.brentq`` and ``ops.newton`` on floats, arrays and in a graph; failures give NaN."""

import math

import numpy as np
import pytest
from scipy import optimize

from gemini import ops
from gemini.compiler.graph import Graph
from gemini.compiler.graph.passes.cse import eliminate_common_subexpressions
from gemini.errors import ValidationError
from tests.fixtures.equivalence import RTOL
from tests.fixtures.errors import raises
from tests.fixtures.graph_run import graph_outputs


def _cubic(x, shift):
    return x**3 - shift


def _cubic_slope(x, shift):
    return 3 * x**2


def _scaled_root(low, high, shift):
    return ops.brentq(_cubic, low, high, args=(shift,))


def test_brentq_on_floats_is_scipy_brentq():
    """The Python backend returns the bits of ``scipy.optimize.brentq`` on the same arguments."""
    expected = optimize.brentq(_cubic, 0.0, 5.0, args=(2.0,), xtol=1e-9)
    assert ops.brentq(_cubic, 0.0, 5.0, args=(2.0,), xtol=1e-9) == expected


def test_brentq_on_arrays_matches_the_python_path_per_row():
    """Each row of an array solve equals the scalar solve of that row."""
    shift = np.array([0.5, 2.0, 8.0, 27.0])
    low, high = np.zeros(4), np.full(4, 5.0)
    roots = ops.brentq(_cubic, low, high, args=(shift,), xtol=1e-9)
    expected = [ops.brentq(_cubic, 0.0, 5.0, args=(float(s),), xtol=1e-9) for s in shift]
    np.testing.assert_allclose(roots, expected, rtol=RTOL, atol=0)
    assert ops.brentq(_cubic, 0.0, 5.0, args=(shift,)).shape == (4,)


def test_a_bracket_without_a_sign_change_is_nan_not_an_error():
    """Rows outside the bracket are NaN on both backends and do not stop the other rows."""
    assert math.isnan(ops.brentq(_cubic, 0.0, 1.0, args=(8.0,)))
    roots = ops.brentq(_cubic, np.zeros(3), np.ones(3), args=(np.array([0.5, 8.0, 0.1]),))
    assert np.isnan(roots).tolist() == [False, True, False]
    assert roots[0] == pytest.approx(0.5 ** (1 / 3), rel=RTOL)


def test_a_bound_that_is_a_root_is_returned():
    """A root at either end of the bracket is returned as scipy does."""
    assert ops.brentq(_cubic, 0.0, 2.0, args=(8.0,)) == 2.0
    assert ops.brentq(_cubic, np.array([2.0]), np.array([3.0]), args=(8.0,))[0] == 2.0


def test_no_convergence_in_the_iteration_budget_is_nan():
    """Too few iterations give NaN on both backends."""
    assert math.isnan(ops.brentq(_cubic, 0.0, 5.0, args=(2.0,), maxiter=1))
    assert np.isnan(ops.brentq(_cubic, np.zeros(2), np.full(2, 5.0), args=(2.0,), maxiter=1)).all()


def test_brentq_checks_its_settings():
    """A tolerance scipy would refuse is a configuration error, not a silent NaN."""
    with raises(ValidationError, "invalid_design", match="xtol = 0"):
        ops.brentq(_cubic, 0.0, 5.0, args=(2.0,), xtol=0)


def test_newton_matches_the_scalar_loop_per_row():
    """An array Newton solve equals the scalar loop of each row, including the stopping step."""
    shift = np.array([0.5, 2.0, 8.0, 27.0])
    roots = ops.newton(_cubic, np.full(4, 3.0), _cubic_slope, args=(shift,))
    expected = [ops.newton(_cubic, 3.0, _cubic_slope, args=(float(s),)) for s in shift]
    np.testing.assert_allclose(roots, expected, rtol=RTOL, atol=0)
    assert roots[2] == pytest.approx(2.0, rel=1e-5)


def test_newton_stops_before_the_last_step_and_at_the_iteration_limit():
    """The returned value is the iterate before the step that met the tolerance."""
    value = 3.0
    while abs(value - (value**3 - 8) / (3 * value**2) - value) >= 1e-6 * value:
        value -= (value**3 - 8) / (3 * value**2)
    assert ops.newton(_cubic, 3.0, _cubic_slope, args=(8.0,)) == value
    assert ops.newton(_cubic, 3.0, _cubic_slope, args=(8.0,), max_iterations=0) == 3.0
    assert ops.newton(_cubic, np.array([3.0]), _cubic_slope, args=(8.0,), max_iterations=2) == (
        ops.newton(_cubic, 3.0, _cubic_slope, args=(8.0,), max_iterations=2)
    )


def test_a_failing_newton_iteration_is_nan():
    """A zero slope or a non-finite iterate gives NaN on both backends."""
    assert math.isnan(ops.newton(_cubic, 0.0, _cubic_slope, args=(8.0,)))
    assert np.isnan(ops.newton(_cubic, np.array([0.0, math.nan]), _cubic_slope, args=(8.0,))).all()


def test_brentq_in_a_graph_records_one_solver_node_and_matches_arrays():
    """A traced solve is one node with the function in its attributes and runs on both backends."""
    graph = Graph("solve")
    shift = graph.input("shift", "inlet")
    graph.output("root", _scaled_root(0.0, 5.0, shift * 2))
    solvers = [node for node in graph.nodes if node.kind == "solver"]
    assert [node.op for node in solvers] == ["brentq"]
    assert solvers[0].attributes["function"] is _cubic
    feeds = np.array([0.25, 1.0, 100.0])
    root = graph_outputs(graph, {"shift": feeds})["root"]
    expected = [ops.brentq(_cubic, 0.0, 5.0, args=(2 * s,)) for s in feeds.tolist()]
    np.testing.assert_allclose(root, expected, rtol=RTOL, atol=0, equal_nan=True)
    assert np.isnan(root[2])
    assert graph_outputs(graph, {"shift": 1.0}, "python")["root"] == expected[1]


def test_newton_in_a_graph_and_common_subexpressions_keep_solver_nodes():
    """Two identical traced solves stay two nodes; the traced Newton equals the array one."""
    graph = Graph("newton")
    shift = graph.input("shift", "inlet")
    first = ops.newton(_cubic, 3.0 + shift * 0, _cubic_slope, args=(shift,))
    second = ops.newton(_cubic, 3.0 + shift * 0, _cubic_slope, args=(shift,))
    graph.output("first", first)
    graph.output("second", second)
    eliminate_common_subexpressions(graph)
    assert sum(node.kind == "solver" for node in graph.nodes) == 2
    feeds = np.array([1.0, 8.0])
    values = graph_outputs(graph, {"shift": feeds})
    np.testing.assert_allclose(
        values["first"], ops.newton(_cubic, np.full(2, 3.0), _cubic_slope, args=(feeds,))
    )


def test_brentq_does_not_swallow_a_failed_check_on_floats():
    """A residual whose check fails raises on floats, as it does on arrays."""
    from gemini.errors import PhysicsError

    def residual(x):
        ops.check(x > 0.5, PhysicsError, "residual: x = {x}", x=x)
        return x - 0.75

    with pytest.raises(PhysicsError):
        ops.brentq(residual, 0.0, 1.0)
    with pytest.raises(PhysicsError):
        ops.brentq(residual, np.array([0.0]), np.array([1.0]))
