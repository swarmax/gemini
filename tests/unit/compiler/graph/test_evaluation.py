"""One evaluation: NumPy and Python backends agree on values, results and failing rows."""

import numpy as np
import pytest

import gemini as gm
from gemini import runtime
from gemini.compiler.graph import GraphCache, evaluate, graph_feeds
from gemini.errors import PhysicsError, ValidationError


def _inlet(rows):
    return gm.Stream(
        m_dot=np.ones(rows),
        T=np.linspace(300.0, 310.0, rows),
        p=np.linspace(1e5, 2e5, rows),
        fluid=gm.WATER,
    )


def _evaluation(module, inputs, rows, backend=None, cache=None):
    inlets = {"fluid_in": _inlet(rows)}
    graph = (cache or GraphCache()).graph(module, {"fluid_in": inlets["fluid_in"].fluid})
    feeds = graph_feeds(graph, module, inlets, inputs)
    with runtime.settings(backend=backend):
        return evaluate(graph, feeds, rows, module=module)


def _leaves(result):
    return {path: leaf for path, leaf in result.leaves().items()}


def test_python_backend_matches_numpy_on_a_composite(line):
    """Outputs, outlets and children of every module agree within 1e-12; ratios keep NaN."""
    line.first.set_params("", {"scale": 0.0})
    inputs = {"boost": np.array([1.0, 2.0, 3.0]), "second.draw": np.array([2.0, 0.0, 5.0])}
    fast = _evaluation(line, inputs, 3).result
    slow = _evaluation(line, inputs, 3, "python").result
    assert fast.children.keys() == slow.children.keys() == {"first", "gain", "second"}
    for name in ("rise", "pressure"):
        assert slow.outputs[name] == pytest.approx(fast.outputs[name], rel=1e-12)
    assert np.isnan(slow.outputs["efficiency"][1]) and np.isnan(fast.outputs["efficiency"][1])
    for path, child in _leaves(fast).items():
        expected = child.outlets.fluid_out.p
        assert _leaves(slow)[path].outlets.fluid_out.p == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("backend", [None, "python"])
def test_result_rows_equal_direct_calls(line, backend):
    """``row(i)`` of the mapped tree equals a direct call, children included."""
    boosts = np.array([1.0, 2.0, 3.0])
    result = _evaluation(line, {"boost": boosts}, 3, backend).result
    inlet = _inlet(3)
    for index in range(3):
        stream = gm.Stream(m_dot=1.0, T=inlet.T[index], p=inlet.p[index], fluid=inlet.fluid)
        direct = line(fluid_in=stream, boost=boosts[index])
        row = result.row(index)
        assert row.outputs.rise == direct.outputs.rise
        assert row.children["gain"].outputs.rise == direct.children["gain"].outputs.rise
        assert row.outlets.fluid_out.p == direct.outlets.fluid_out.p


@pytest.mark.parametrize("backend", [None, "python"])
def test_failing_rows_carry_the_check_message_of_that_row(line, backend):
    """Each failing row has the exact exception; others are unaffected."""
    evaluation = _evaluation(line, {"boost": np.array([1.0, -1.0, 2.0, -2.0])}, 4, backend)
    assert evaluation.failed.tolist() == [False, True, False, True]
    first, second = evaluation.error(1), evaluation.error(3)
    assert isinstance(first, PhysicsError) and "gain: gain = -1.0" in str(first)
    assert "gain: gain = -2.0" in str(second)
    assert any("raised by the check" in note for note in first.__notes__)


@pytest.mark.parametrize("backend", [None, "python"])
def test_declared_limits_use_the_wording_of_declaration_validate(bounded, backend):
    """A violated bound gives the text and class of ``Declaration.validate`` for that row."""
    inputs = {"setpoint": np.array([1e5, -5.0]), "ambient": 300.0}
    evaluation = _evaluation(bounded, inputs, 2, backend)
    expected = None
    try:
        bounded.get("setpoint").validate(-5.0)
    except ValidationError as error:
        expected = str(error)
    assert evaluation.failed.tolist() == [False, True]
    assert isinstance(evaluation.error(1), ValidationError)
    assert str(evaluation.error(1)) == expected


def test_vectors_literals_and_nullable_outputs_are_arrays(bounded):
    """A list output is (rows, n), a None branch is NaN and the dtype is the declared one."""
    inputs = {"setpoint": np.array([1e5, 2e5]), "ambient": np.array([300.0, 2000.0])}
    result = _evaluation(bounded, inputs, 2).result
    assert result.outputs["profile"].shape == (2, 2)
    assert np.isnan(result.outputs["share"][1]) and result.row(1).outputs.share is None
    assert result.outputs["margin"].dtype == np.float64
