"""The runner evaluates arrays in one traced call or falls back to untraced calls."""

import numpy as np
import pytest

import gemini as gm
from gemini import ops
from gemini.compiler.graph import GraphCache, run, run_function
from gemini.compiler.graph.errors import TraceError
from gemini.errors import PhysicsError
from gemini.ops import Constant

from .conftest import Chain, Gain, Opaque, Stubborn, Switcher, Tank, Vectored


def _rows(gain, inlet, frequency):
    return [
        gain(
            fluid_in=gm.Stream(m_dot=1.0, T=inlet.T[row], p=inlet.p[row], fluid=inlet.fluid),
            gain=frequency[row],
        )
        for row in range(3)
    ]


def test_traced_run_matches_untraced_calls(gain, inlet):
    """Every output and outlet field equals the row-by-row results."""
    controls = np.array([0.0, 1.0, 2.0])
    result = run(gain, {"fluid_in": inlet}, {"gain": controls})
    expected = _rows(gain, inlet, controls)
    assert result.breaks == [] and result.graph is not None
    assert result.outputs["rise"].tolist() == [row.outputs.rise for row in expected]
    assert result.outputs["boost"].tolist() == [row.outputs.boost for row in expected]
    assert result.outlets["fluid_out"]["p"].tolist() == [
        row.outlets.fluid_out.p for row in expected
    ]


def test_graph_break_runs_untraced_with_the_same_results(gain, inlet):
    """A pre-hook breaks the graph; the reason is reported and the values are unchanged."""
    gain.register_forward_pre_hook(lambda module, inlets: None)
    result = run(gain, {"fluid_in": inlet}, {"gain": 1.0})
    assert result.graph.root_break and "pre-hooks" in result.breaks[0]
    assert result.outputs["rise"].tolist() == [6.0, 6.0, 6.0]


def test_a_reading_hook_makes_the_root_a_break_that_sees_every_real_row(gain, inlet):
    """The trace calls the hook once on traced values to classify it; then every row is real."""
    seen = []
    gain.register_forward_hook(lambda module, inlets, outlets: seen.append(module.rise))
    result = run(gain, {"fluid_in": inlet}, {"gain": 1.0})
    assert "only reads" in result.breaks[0] and seen[1:] == [6.0, 6.0, 6.0]


def test_errors_raise_after_the_run(gain, inlet):
    """A negative gain raises the untraced error for its first row."""
    with pytest.raises(PhysicsError, match="gain: gain = -1.0"):
        run(gain, {"fluid_in": inlet}, {"gain": np.array([1.0, -1.0, -2.0])})


def test_structural_parameter_decides_the_traced_shape(stepper, inlet):
    """A structural count unrolls the loop of the trace; the numeric increment stays an input."""
    cache = GraphCache()
    for steps, increment in ((2, 1.0), (3, 10.0)):
        stepper.set_params("", {"steps": steps, "increment": increment})
        result = run(stepper, {"fluid_in": inlet}, cache=cache)
        assert result.outlets["fluid_out"]["p"].tolist() == (inlet.p + steps * increment).tolist()
    assert cache.traces == 2


def test_module_without_inlets_takes_its_row_count_from_the_inputs(source):
    """The control array sets the rows; a graph break gives the same values row by row."""
    controls = np.array([1.0, 2.0, 3.0])
    result = run(source, {}, {"rate": controls})
    assert result.outputs["double"].tolist() == [2.0, 4.0, 6.0]
    assert result.outlets["fluid_out"]["m_dot"].tolist() == [1.0, 2.0, 3.0]
    assert result.outlets["fluid_out"]["T"].tolist() == [300.0] * 3
    source.register_forward_pre_hook(lambda module, inlets: None)
    assert run(source, {}, {"rate": controls}).outputs["double"].tolist() == [2.0, 4.0, 6.0]


def test_module_without_inlets_or_arrays_has_one_row(source):
    """Scalar inputs and no inlets give a single row."""
    assert run(source, {}, {"rate": 5.0}).outputs["double"].tolist() == [10.0]


def test_pre_hooks_and_reading_hooks_see_every_row_of_the_break(gain, inlet):
    """A pre-hook and a reading hook run in a call's order for each row of the break."""
    seen = []
    gain.register_forward_pre_hook(lambda module, inlets: seen.append("pre"))
    gain.register_forward_hook(lambda module, inlets, outlets: seen.append(module.rise))
    result = run(gain, {"fluid_in": inlet}, {"gain": 1.0})
    assert result.graph.root_break
    assert seen == ["pre", 6.0, "pre", 6.0, "pre", 6.0]


def _line_rows(line, inlet, boosts, draws):
    rows = []
    for row in range(3):
        line.second.draw = draws[row]
        stream = gm.Stream(m_dot=1.0, T=inlet.T[row], p=inlet.p[row], fluid=inlet.fluid)
        rows.append(line(fluid_in=stream, boost=boosts[row]))
    return rows


def test_composite_run_matches_untraced_calls(line, inlet):
    """Output.of, outlet fields, automatic sums, ratios and outlets equal the row-by-row calls."""
    boosts, draws = [1.0, 2.0, 3.0], np.array([2.0, 0.0, 5.0])
    line.first.set_params("", {"scale": 0.0})
    result = run(line, {"fluid_in": inlet}, {"boost": np.array(boosts), "second.draw": draws})
    expected = _line_rows(line, inlet, boosts, draws)
    assert result.graph is not None and result.breaks == []
    for name in ("rise", "pressure"):
        assert result.outputs[name].tolist() == [row.outputs[name] for row in expected]
    ratios = [row.outputs.efficiency for row in expected]
    assert ratios[1] is None
    assert np.isnan(result.outputs["efficiency"][1])
    assert result.outputs["efficiency"][[0, 2]].tolist() == [ratios[0], ratios[2]]
    assert result.outlets["fluid_out"]["p"].tolist() == [
        row.outlets.fluid_out.p for row in expected
    ]


def test_composite_child_inputs_come_from_the_tree(line, inlet):
    """A child control not supplied by the root is fed from the child's persisted value."""
    line.second.draw = 4.0
    result = run(line, {"fluid_in": inlet}, {"boost": 1.0})
    assert result.outputs["electricity"].tolist() == [8.0] * 3


def test_composite_errors_raise_the_child_error(line, inlet):
    """A negative control of a child raises the child's error class and message."""
    with pytest.raises(PhysicsError, match="gain: gain = -1.0"):
        run(line, {"fluid_in": inlet}, {"boost": np.array([1.0, -1.0, 2.0])})


def _chain_rows(chain, inlet, drives):
    rows = []
    for row in range(3):
        stream = gm.Stream(
            m_dot=inlet.m_dot[row], T=inlet.T[row], p=inlet.p[row], fluid=inlet.fluid
        )
        rows.append(chain(fluid_in=stream, drive=drives[row]))
    return rows


@pytest.fixture
def chain_inlet():
    """Return a three-row water inlet for the chains."""
    return gm.Stream(
        m_dot=np.array([1.0, 2.0, 3.0]),
        T=np.array([300.0, 310.0, 320.0]),
        p=np.array([1e5, 2e5, 3e5]),
        fluid=gm.WATER,
    )


def _break_middles():
    stubborn = Stubborn().set_params("", {"scale": 3.0})
    hooked = Gain().set_params("", {"scale": 3.0})
    hooked.register_forward_pre_hook(lambda module, inlets: None)
    return {"stateful": Tank(), "untraceable": stubborn, "pre-hooked": hooked}


@pytest.mark.parametrize("kind", ["stateful", "untraceable", "pre-hooked"])
def test_a_leaf_break_keeps_the_rest_in_the_graph(kind, chain_inlet):
    """The child runs untraced per row; its values flow into formulas, sums and outlets."""
    chain = Chain(_break_middles()[kind])
    drives = np.array([1.0, 2.0, 3.0])
    result = run(chain, {"fluid_in": chain_inlet}, {"drive": drives})
    expected = _chain_rows(chain, chain_inlet, drives)
    assert result.graph is not None and result.breaks == []
    assert [path for path, _ in result.graph.breaks] == ["middle"]
    assert result.graph.nodes[0].op != "break" and "break(" in result.graph.describe()
    for name in ("value", "pressure"):
        assert result.outputs[name].tolist() == [row.outputs[name] for row in expected]
    assert result.outlets["fluid_out"]["p"].tolist() == [
        row.outlets.fluid_out.p for row in expected
    ]


def test_a_failing_break_row_raises_its_own_exception(chain_inlet):
    """The exception of the first failing row of the child is raised as it was."""
    chain = Chain(Stubborn().set_params("", {"scale": 3.0}))
    with pytest.raises(PhysicsError, match="middle: gain = -2.0"):
        run(chain, {"fluid_in": chain_inlet}, {"drive": np.array([1.0, -2.0, -3.0])})


def test_a_break_node_runs_on_the_python_backend_too(chain_inlet):
    """With scalar rows the break node returns plain Python values."""
    chain = Chain(Tank())
    expected = run(chain, {"fluid_in": chain_inlet}, {"drive": 1.0})
    actual = run(chain, {"fluid_in": chain_inlet}, {"drive": 1.0}, backend="python")
    for name, values in expected.outputs.items():
        assert actual.outputs[name].tolist() == values.tolist()


def test_a_pre_hook_of_a_break_runs_once_per_row(chain_inlet):
    """A pre-hooked child is called on the plain path for every row, hooks included."""
    calls = []
    middle = Gain().set_params("", {"scale": 3.0})
    middle.register_forward_pre_hook(lambda module, inlets: calls.append(1))
    run(Chain(middle), {"fluid_in": chain_inlet}, {"drive": 1.0})
    assert len(calls) == 3


def test_a_composite_child_that_cannot_be_traced_breaks_the_whole_root(chain_inlet):
    """A composite is never a node: its leaves' records feed the parent, so the root breaks."""
    chain = Chain(Opaque())
    result = run(chain, {"fluid_in": chain_inlet}, {"drive": 1.0})
    assert result.graph.root_break and "float()" in result.breaks[0]


def test_a_row_whose_outlet_fluid_differs_from_the_probe_fails(chain_inlet):
    """The static outlet fluid comes from a probe; another fluid on a row is a failed row."""
    chain = Chain(Switcher())
    with pytest.raises(TraceError, match="fluid differs from the traced one"):
        run(chain, {"fluid_in": chain_inlet}, {"drive": 1.0})


def test_list_outputs_are_stacked_per_row(chain_inlet):
    """A list-valued output comes back as one array of shape (rows, length)."""
    middle = Vectored()
    result = run(middle, {"fluid_in": chain_inlet})
    assert result.breaks == [] and result.outputs["profile"].shape == (3, 2)
    assert result.outputs["profile"].tolist() == [[1e5, 1e5 + 1], [2e5, 2e5 + 1], [3e5, 3e5 + 1]]
    row = middle(fluid_in=gm.Stream(m_dot=1.0, T=300.0, p=2e5, fluid=gm.WATER))
    assert row.outputs.profile == [2e5, 2e5 + 1]


def test_a_control_without_a_value_is_nan_in_the_graph(optional):
    """An optional control that is ``None`` is fed as NaN, like every graph ``None``."""
    assert run(optional, {}, {"rate": np.array([1.0, 2.0])}).outputs["double"].tolist() == [
        2.0,
        4.0,
    ]
    assert run(optional, {}, {}).outputs["double"].tolist() == [-1.0]


MESSAGE = "pipe: x = {x} m; expected x >= 0"


@ops.physics
def doubled(x):
    """Double ``x``, which must not be negative."""
    ops.check(x >= 0, PhysicsError, MESSAGE, x=x)
    return x * 2.0


@ops.physics
def gated(x, gate):
    """Return zero where ``gate`` is positive, else the checked value."""
    return ops.where(gate > 0.0, 0.0, doubled(x))


@ops.physics
def branched(x):
    """Branch on a checked value."""
    return ops.where(doubled(x) > 1.0, 1.0, 2.0)


@ops.physics
def combined(x, y):
    """Mix a checked value with floats, constants, abs and a nested physics function."""
    return abs(doubled(x)) / (y + 1.0) + SCALE * doubled(y) + sum([doubled(x), 1.0])


@ops.physics
def pair(x, y):
    """Return a tuple, a dict and a list of results."""
    return (gated(x, y), {"double": doubled(y)}, [doubled(y) + 1.0])


@ops.physics
def checked_pass_through(x):
    """Check ``x`` and return the argument itself."""
    ops.check(x >= 0, PhysicsError, MESSAGE, x=x)
    return x


@ops.physics
def no_leak(x, gate):
    """Another use of the checked argument outside the checked branch stays clean."""
    return ops.where(gate > 0.0, x + 1.0, checked_pass_through(x))


@ops.physics
def two_failures(x, y):
    """Fail on both operands: the check that ran first is the error."""
    return doubled(x) + doubled(y)


@ops.physics
def two_failures_reversed(x, y):
    """Fail on both operands, the other way round."""
    return doubled(y) + doubled(x)


def inline_check(x, gate):
    """Raise at once for a check outside any physics function, whatever the gate does."""
    ops.check(x >= 0, PhysicsError, MESSAGE, x=x)
    return ops.where(gate > 0.0, 0.0, x * 2.0)


SCALE = Constant("SCALE", 2.0, "-", "a test constant")
OUTCOME_CASES = [
    (no_leak, (-1.0, 1.0)),
    (no_leak, (-1.0, -1.0)),
    (no_leak, (2.0, -1.0)),
    (two_failures, (-1.0, -2.0)),
    (two_failures, (1.0, -2.0)),
    (two_failures_reversed, (-1.0, -2.0)),
    (two_failures_reversed, (-1.0, 2.0)),
    (inline_check, (-1.0, 1.0)),
    (inline_check, (1.0, 1.0)),
    (gated, (-1.0, 1.0)),
    (gated, (-1.0, -1.0)),
    (gated, (2.0, -1.0)),
    (branched, (-1.0,)),
    (branched, (0.2,)),
    (branched, (3.0,)),
    (combined, (1.0, 2.0)),
    (combined, (-1.0, 2.0)),
    (combined, (1.0, -2.0)),
    (pair, (1.0, 2.0)),
    (pair, (-1.0, 1.0)),
    (pair, (1.0, -1.0)),
]


def outcome(call):
    """Return the value of ``call()``, or the class and message of its error."""
    try:
        return call()
    except PhysicsError as error:
        return type(error), str(error)


@pytest.mark.parametrize(("function", "args"), OUTCOME_CASES)
def test_run_function_and_an_eager_call_give_the_same_outcome(function, args):
    """A trace through ``run_function`` and the eager scope drop and keep the same errors."""
    eager = outcome(lambda: function(*args))
    traced = outcome(lambda: run_function(function, *args))
    np.testing.assert_equal(traced, eager)


def test_run_function_lets_an_array_row_cross_a_where_around_a_check():
    """Rows the gate stops do not raise; the first failing selected row does."""
    x = np.array([-1.0, 2.0, -3.0])
    assert run_function(gated, x, np.array([1.0, -1.0, 1.0])).tolist() == [0.0, 4.0, 0.0]
    with pytest.raises(PhysicsError, match=r"x = -2\.0 m"):
        run_function(gated, np.array([-1.0, -2.0, 3.0]), np.array([1.0, -1.0, -1.0]))
    with pytest.raises(PhysicsError, match=r"x = -1\.0 m"):
        doubled(x)


def test_run_function_keeps_the_structure_of_the_result():
    """Tuples, dicts and lists come back with arrays; structural arguments pass unchanged."""
    first, second, third = run_function(pair, np.array([1.0, 2.0]), np.array([3.0, 4.0]))
    assert first.tolist() == [0.0, 0.0] and second["double"].tolist() == [6.0, 8.0]
    assert third[0].tolist() == [7.0, 9.0] and isinstance(third, list)

    def scaled(x, factor, label):
        assert label == "kg"
        return x * factor

    assert run_function(scaled, np.array([1.0, 2.0]), 3, "kg").tolist() == [3.0, 6.0]
    assert run_function(scaled, 2.0, 3, "kg") == 6.0


def test_a_physics_function_that_failed_on_constants_cannot_be_traced():
    """A failure that does not depend on any input is a trace error, as eager it raises."""

    def constant_failure(x):
        return x + doubled(-1.0)

    with pytest.raises(PhysicsError, match="x = -1.0 m"):
        constant_failure(1.0)
    with pytest.raises(TraceError, match="check failed on constant values"):
        run_function(constant_failure, 1.0)
