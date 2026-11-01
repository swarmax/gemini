"""Break nodes record the plain path of a child and stack its results row by row."""

import numpy as np

import gemini as gm
from gemini.compiler.graph import Graph
from gemini.compiler.graph.breaks import PROBE, evaluate_break, record_break
from gemini.types.ports import Ports
from tests.fixtures.graph_run import graph_outputs


def _break_graph(tank):
    graph = Graph("test")
    inlets = Ports(
        {
            "fluid_in": gm.Stream._trusted(
                m_dot=graph.input("fluid_in.m_dot", "inlet"),
                T=graph.input("fluid_in.T", "inlet"),
                p=graph.input("fluid_in.p", "inlet"),
                fluid=tank.fluid,
            )
        }
    )
    outlets, outputs, _, _ = record_break(graph, tank, "", inlets, {}, True, "stateful")
    graph.output("content", outputs["content"])
    graph.output("p", outlets.fluid_out.p)
    return graph


def test_record_break_adds_the_node_its_outputs_and_the_guarding_check(tank):
    """One break node, one output node per field plus the success mask, and one check."""
    graph = _break_graph(tank)
    ops_used = [node.op for node in graph.nodes if node.kind == "break"]
    assert ops_used == ["break"] + ["break_output"] * 5
    assert [node.op for node in graph.checks] == ["check"]
    assert graph.breaks == [("tank", "stateful")]
    assert PROBE["T"] == 300.0


def test_evaluate_break_stacks_rows_and_marks_failures(tank):
    """A row that raises is NaN and keeps its exception; other rows are unchanged."""
    graph = _break_graph(tank)
    node = graph.nodes[3]
    operands = [np.array([1.0, 5.0, 2.0]), np.array([300.0, -1.0, 300.0]), np.full(3, 1e5)]
    result = evaluate_break(node, operands, tank)
    assert result.ok.tolist() == [True, False, True]
    assert result.column(("outputs", "content"))[[0, 2]].tolist() == [1.0, 2.0]
    assert np.isnan(result.column(("outputs", "content"))[1]) and 1 in result.exceptions


def test_interpreter_gives_scalar_results_for_scalar_operands(tank):
    """On the Python backend the break node returns plain numbers."""
    graph = _break_graph(tank)
    feeds = {"fluid_in.m_dot": 2.0, "fluid_in.T": 300.0, "fluid_in.p": 1e5}
    values = graph_outputs(graph, feeds, "python", tank)
    assert values["content"] == 2.0 and values["p"] == 1e5
