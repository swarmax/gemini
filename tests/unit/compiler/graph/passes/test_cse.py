"""Common-subexpression elimination keeps results and errors and merges what is identical."""

import copy
import math

import numpy as np
import pytest

import gemini as gm
from gemini import ops
from gemini.compiler.graph import Graph, GraphCache, run
from gemini.compiler.graph.limits import certain
from gemini.compiler.graph.passes import eliminate_common_subexpressions
from gemini.errors import PhysicsError
from tests.fixtures.graph_run import graph_outputs

COLUMNS = ["suction.m_dot", "suction.T", "suction.p", "frequency"]
XS = np.array([-3.0, -1.0, 0.5, 2.0])


def _outcome(graph, xs=XS):
    """Return the outputs of ``graph`` over ``xs``, or the error it raises as (class, text)."""
    try:
        values = graph_outputs(graph, {"x": xs})
    except PhysicsError as error:
        return type(error), str(error)
    return {name: np.asarray(value).tolist() for name, value in values.items()}


def _merged(build):
    """Return the unmerged and the merged graph of ``build``, a function of one input graph."""
    graphs = []
    for optimize in (False, True):
        graph = Graph("test")
        with ops.scope.tracing(graph):
            build(graph, graph.input("x", "inlet"))
        certain(graph, graph.unframed)
        if optimize:
            eliminate_common_subexpressions(graph)
        graphs.append(graph)
    return graphs


def _count(graph, op):
    return sum(node.op == op for node in graph.nodes)


def _check_positive(value, label="v"):
    ops.check(value > -2, PhysicsError, label + " = {v}; expected > -2", v=value)


@ops.physics
def _checked_double(x):
    """Return ``x * 2``, guarded by a check of its own value like a physics function's result."""
    value = x * 2
    _check_positive(value)
    return value


@pytest.fixture(scope="module")
def week(fast_frame):
    """Return the first two days of ESP inputs in SI: mass flow, T, p and frequency."""
    frame = fast_frame.iloc[: 2 * 96][[f"doublet.esp.{column}" for column in COLUMNS]].dropna()
    return frame.to_numpy()


@pytest.fixture
def esp(shared_plant):
    """Return an isolated copy of the shared plant's ESP."""
    return copy.deepcopy(shared_plant.doublet.esp)


def _suction(esp, rows):
    density = esp.fluid.properties(None, None).density
    return gm.Stream(
        m_dot=gm.units.Quantity(rows[:, 0] * density, "kg/s"),
        T=gm.units.Quantity(rows[:, 1], "K"),
        p=gm.units.Quantity(rows[:, 2], "Pa"),
        fluid=esp.fluid,
    )


def test_esp_graph_shrinks_and_keeps_its_results(esp, week):
    """The merged ESP graph is smaller and its outputs equal the unmerged ones exactly."""
    plain, merged = GraphCache(optimize=False), GraphCache()
    inputs = {"frequency": week[:, 3]}
    expected = run(esp, {"fluid_in": _suction(esp, week)}, inputs, cache=plain)
    actual = run(esp, {"fluid_in": _suction(esp, week)}, inputs, cache=merged)
    assert len(actual.graph.nodes) < len(expected.graph.nodes)
    assert len(actual.graph.checks) <= len(expected.graph.checks)
    for name, values in expected.outputs.items():
        np.testing.assert_array_equal(actual.outputs[name], values)
    assert "outputs.power" in actual.graph.describe()


def test_esp_graph_raises_the_same_error(esp, week):
    """A negative mass flow raises the same class and message with and without the pass."""
    rows = week.copy()
    rows[3, 0] = -abs(rows[3, 0]) - 1.0
    messages = []
    for cache in (GraphCache(optimize=False), GraphCache()):
        with pytest.raises(PhysicsError) as raised:
            run(esp, {"fluid_in": _suction(esp, rows)}, {"frequency": rows[:, 3]}, cache=cache)
        messages.append(str(raised.value))
    assert messages[0] == messages[1]


def test_identical_nodes_merge_and_indices_follow_positions():
    """Repeated expressions become one node; node order, indices and outputs stay consistent."""

    def build(graph, x):
        first, second = x * 2 + 1, x * 2 + 1
        graph.output("a", first)
        graph.output("b", second * 3)
        graph.output("c", first * 3)

    plain, merged = _merged(build)
    assert len(plain.nodes) == 7 and len(merged.nodes) == 4
    assert [node.index for node in merged.nodes] == list(range(4))
    assert merged.outputs["b"] is merged.outputs["c"]
    assert _outcome(plain) == _outcome(merged)
    assert merged.describe().count("mul(") == 2


def test_inputs_are_never_merged():
    """Two inputs stay two nodes, and a constant stays one input node."""
    graph = Graph("test")
    first, second = graph.input("x", "inlet"), graph.input("y", "inlet")
    graph.output("sum", first + second)
    graph.output("again", first + second)
    eliminate_common_subexpressions(graph)
    assert len(graph.inputs) == 2 and len(graph.nodes) == 3


def test_literals_of_different_type_or_sign_do_not_merge():
    """``1``, ``1.0`` and ``True`` differ, ``0.0`` and ``-0.0`` differ, NaN equals itself."""

    def build(graph, x):
        for name, literal in enumerate((1, 1.0, True, 0.0, -0.0, math.nan, float("nan"))):
            graph.output(str(name), x + literal)

    _, merged = _merged(build)
    assert len(merged.nodes) == 1 + 6
    assert merged.outputs["5"] is merged.outputs["6"]
    assert len({id(merged.outputs[str(name)]) for name in range(5)}) == 5


def test_numpy_scalars_differ_from_python_numbers():
    """A NumPy float and a Python float are different literals even at the same value."""

    def build(graph, x):
        graph.output("a", x + 1.5)
        graph.output("b", x + np.float64(1.5))
        graph.output("c", x + np.float32(1.5))

    _, merged = _merged(build)
    assert len(merged.nodes) == 4


def test_repeated_checks_merge_renumber_and_follow_merged_values():
    """Twin checks collapse to one; codes stay 1..n and message values point at survivors."""

    def build(graph, x):
        first, second = x * 2, x * 2
        _check_positive(first)
        ops.check(x > -10, PhysicsError, "x = {x}", x=x)
        _check_positive(second)
        graph.output("y", first + second)

    plain, merged = _merged(build)
    assert len(plain.checks) == 3 and len(merged.checks) == 2
    assert [check.code for check in merged.checks] == [1, 2]
    assert all(
        value.node in merged.nodes
        for check in merged.checks
        for value in check.attributes["values"].values()
    )
    assert merged.nodes[merged.outputs["y"].index] is merged.outputs["y"]
    assert _outcome(plain) == _outcome(merged)
    assert _outcome(plain)[0] is PhysicsError


def test_checks_with_other_message_or_values_do_not_merge():
    """A different message, error class or message value keeps the checks apart."""

    def build(graph, x):
        ops.check(x > 0, PhysicsError, "a = {v}", v=x)
        ops.check(x > 0, PhysicsError, "b = {v}", v=x)
        ops.check(x > 0, PhysicsError, "a = {v}", v=x * 2)
        ops.check(x > 0, PhysicsError, "a = {v}", v=1.0)
        ops.check(x > 0, PhysicsError, "a = {v}", v=1)
        graph.output("y", x)

    _, merged = _merged(build)
    assert len(merged.checks) == 5


def test_lowest_code_still_wins_after_merging():
    """With several failing checks the first one in creation order is still raised."""

    def build(graph, x):
        ops.check(x > 0, PhysicsError, "first {v}", v=x)
        ops.check(x > 1, PhysicsError, "second {v}", v=x)
        ops.check(x > 0, PhysicsError, "first {v}", v=x)
        graph.output("y", x)

    plain, merged = _merged(build)
    assert _outcome(plain, np.array([0.5])) == _outcome(merged, np.array([0.5]))
    assert _outcome(merged, np.array([-1.0]))[1] == "first -1.0"


def test_guards_survive_a_merge_of_guarded_and_unguarded_twins():
    """Twins that both reach an output merge and the survivor keeps every guard."""

    def build(graph, x):
        guarded, bare = _checked_double(x), x * 2
        graph.output("a", guarded + 1)
        graph.output("b", bare + 2)

    plain, merged = _merged(build)
    assert len(merged.nodes) == len(plain.nodes) - 1
    survivor = merged.outputs["a"].operands[0]
    assert [check.code for check in survivor.guards] == [1]
    assert _outcome(plain) == _outcome(merged)


def test_guard_lists_are_united_in_order_without_duplicates():
    """Two guarded twins keep the guards of both, once each, lowest code first."""

    def build(graph, x):
        first, second = x * 2, x * 2
        ops.check(first > -9, PhysicsError, "one {v}", v=first)
        ops.check(second > -8, PhysicsError, "two {v}", v=second)
        graph.output("y", first + second)

    plain, merged = _merged(build)
    assert [check.code for check in merged.outputs["y"].guards] == [1, 2]
    assert _outcome(plain, np.array([-4.5])) == _outcome(merged, np.array([-4.5]))
    assert _outcome(merged, np.array([-4.5]))[1] == "one -9.0"


def _where_graph(shared_use):
    def build(graph, x):
        guarded, bare = _checked_double(x), x * 2
        if shared_use:
            graph.output("direct", guarded + 0.0)
        graph.output("y", ops.where(x > 0, guarded, bare))

    return build


def test_guard_never_moves_onto_the_other_where_branch():
    """A check below the true branch must not fire on rows that select the false branch."""
    plain, merged = _merged(_where_graph(shared_use=False))
    assert _count(merged, "mul") == _count(plain, "mul") == 2
    rows = np.array([-3.0, 1.0])
    assert _outcome(plain, rows) == _outcome(merged, rows)
    assert isinstance(_outcome(merged, rows), dict)
    assert _outcome(plain, np.array([-3.0, 1.0, -0.5])) == _outcome(
        merged, np.array([-3.0, 1.0, -0.5])
    )


def test_twins_merge_when_the_guard_reaches_an_output_anyway():
    """The same twins merge when the guarded value also feeds an output outside the branch."""
    plain, merged = _merged(_where_graph(shared_use=True))
    assert _count(merged, "mul") == 1 and _count(plain, "mul") == 2
    for rows in (np.array([-3.0, 1.0]), np.array([1.0, 2.0])):
        assert _outcome(plain, rows) == _outcome(merged, rows)
    assert _outcome(merged, np.array([-3.0]))[0] is PhysicsError


def test_twin_checks_in_the_same_branch_stay_correct():
    """Guarded twins inside one branch are kept apart or merged, never wrong."""

    def build(graph, x):
        def branch():
            first, second = x * 2, x * 2
            _check_positive(first)
            _check_positive(second)
            return first + second

        graph.output("y", ops.where(x > 0, branch(), x))

    plain, merged = _merged(build)
    for rows in (np.array([-3.0, 1.0]), np.array([1.0, 2.0]), np.array([-3.0])):
        assert _outcome(plain, rows) == _outcome(merged, rows)


def test_where_condition_errors_always_surface():
    """A guarded value in the condition of ``where`` reaches the output on every row."""

    def build(graph, x):
        guarded, bare = x * 2, x * 2
        _check_positive(guarded)
        graph.output("y", ops.where(guarded > 0, x, bare))

    plain, merged = _merged(build)
    assert _count(merged, "mul") == 1
    assert _outcome(plain) == _outcome(merged)
    assert _outcome(merged)[0] is PhysicsError


def test_pass_is_idempotent_and_describes_the_graph():
    """A second run changes nothing and the listing still renders."""

    def build(graph, x):
        graph.output("y", (x * 2 + 1) * (x * 2 + 1))

    _, merged = _merged(build)
    before = merged.describe()
    eliminate_common_subexpressions(merged)
    assert merged.describe() == before


def test_cache_merges_by_default_and_not_when_disabled(esp):
    """``GraphCache`` merges once per trace; ``optimize=False`` keeps the traced graph."""
    fluids = {"fluid_in": esp.fluid}
    merged = GraphCache().graph(esp, fluids)
    plain = GraphCache(optimize=False).graph(esp, fluids)
    assert len(merged.nodes) < len(plain.nodes)
    assert [node.index for node in merged.nodes] == list(range(len(merged.nodes)))


def test_composite_graph_shrinks_and_keeps_its_results(twice):
    """A child called twice on the same inlet is computed once; every output stays exact."""
    stream = gm.Stream(
        m_dot=gm.units.Quantity(np.ones(3), "kg/s"),
        T=gm.units.Quantity(np.full(3, 300.0), "K"),
        p=gm.units.Quantity(np.array([1e5, 2e5, 3e5]), "Pa"),
        fluid=twice.fluid,
    )
    plain, merged = GraphCache(optimize=False), GraphCache()
    expected = run(
        twice, {"fluid_in": stream}, {"gain.gain": np.array([1.0, 2.0, 3.0])}, cache=plain
    )
    actual = run(
        twice, {"fluid_in": stream}, {"gain.gain": np.array([1.0, 2.0, 3.0])}, cache=merged
    )
    assert len(actual.graph.nodes) < len(expected.graph.nodes)
    assert len(actual.graph.checks) < len(expected.graph.checks)
    np.testing.assert_array_equal(
        actual.outlets["fluid_out"]["p"], expected.outlets["fluid_out"]["p"]
    )
    assert actual.outlets["fluid_out"]["p"].tolist() == [2e5 + 12, 4e5 + 24, 6e5 + 36]
