"""A loop body owns its nodes and checks; a rollback and a merge keep it consistent."""

from gemini.compiler.graph import GraphCache
from gemini.compiler.graph.body import Body
from tests.unit.compiler.graph.test_loops import _circuit


def test_the_nodes_of_a_pass_belong_to_the_body_and_the_final_pass_to_none():
    """The carries and the nodes of the traced pass are owned; the node itself is outer."""
    graph = GraphCache().graph(_circuit(), {})
    (body,) = graph.bodies
    fixed = next(node for node in graph.nodes if node.op == "fixed_point")
    assert fixed.body is None and fixed.attributes["body"] is body
    assert len(body.carries) == 3 and body.nodes
    assert all(node.body is body for node in body.nodes + body.carries)
    assert body.unframed and all(check.body is body for check in body.checks)


def test_a_rollback_drops_what_was_recorded_after_the_mark():
    """Nodes, checks and unframed checks at or after the index leave the body."""
    graph = GraphCache(optimize=False).graph(_circuit(), {})
    (body,) = graph.bodies
    cut = body.nodes[len(body.nodes) // 2].index
    body.rollback(cut)
    assert all(node.index < cut for node in body.nodes + body.checks + body.unframed)


def test_an_empty_body_has_nothing():
    """A new body holds no node and no check."""
    body = Body()
    assert not (body.nodes or body.checks or body.unframed or body.carries)
