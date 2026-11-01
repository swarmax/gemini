"""Common-subexpression elimination: merge nodes with the same op, operands and attributes.

``eliminate_common_subexpressions(graph)`` rewrites the graph in place in one forward sweep
over the nodes in creation order. A node is a twin of an earlier node when its op, its
operands (after the operands themselves were merged), its literals and its attributes are
identical. Operand identity is a node by the merged node and a literal by type and exact value:
``1``, ``1.0`` and ``True`` differ, ``0.0`` and ``-0.0`` differ, NaN equals itself. Graph
inputs and ops of the ``reduction``, ``interp``, ``solver`` and ``scan`` kinds are never merged.

Errors. A node carries the error codes of its operands and of its ``guards``, and ``where``
keeps only the codes of its selected branch. Merging twins gives the survivor the union of
their guards, which can only add an error to the consumers of one twin. That is harmless when
the added error already reaches a graph output on every row where it fires, because the error
that is raised is the lowest code over all outputs; it is wrong when the twin sat in one
``where`` branch and the error belonged to the other. A node is therefore ``certain`` when it
reaches a graph output through operands that are not a ``where`` branch. Two twins merge only
when each of them is certain or has no guards. A node whose guards stay below a ``where``
branch merges with nothing, so no error moves onto a branch it did not belong to.

Checks merge like any other node: same condition, error class, message and message values. The
merged check keeps the lowest code, codes are renumbered in creation order, and the traced
message values of every check and the proxies of ``Graph.result`` follow the merged nodes. The
pass costs one dictionary lookup per node.
"""

import struct

import numpy as np

from gemini.compiler.graph.node import Node
from gemini.compiler.graph.proxy import Proxy
from gemini.ops import Constant

MERGEABLE_KINDS = ("elementwise", "index", "check")


def eliminate_common_subexpressions(graph):
    """Merge identical nodes of ``graph`` in place, keeping results, errors and node order."""
    numbering = _Numbering(graph)
    for node in graph.nodes:
        numbering.visit(node)
    numbering.finish()


class _Numbering:
    """The state of one sweep: the survivor of every node and what each survivor absorbed."""

    def __init__(self, graph):
        self.graph = graph
        self.certain = _certain_nodes(graph)
        self.survivor = {}
        self.table = {}
        self.kept = []
        self.safe = {}
        self.guarded = {}

    def visit(self, node):
        """Merge ``node`` into an earlier twin if it has one and the merge is safe."""
        node.operands = tuple(self._merged(operand) for operand in node.operands)
        if node.kind == "check":
            node.attributes = self._merged_attributes(node.attributes)
        twin = None
        if node.kind in MERGEABLE_KINDS:
            key = _key(node)
            twin = self.table.setdefault(key, node)
        if twin is None or twin is node or not self._may_merge(twin, node):
            self._keep(node)
            return
        self.survivor[node] = twin
        self.safe[twin] = self.safe[twin] or node in self.certain
        self.guarded[twin] = self.guarded[twin] or bool(node.guards)

    def finish(self):
        """Rebuild the guards, checks, indices and outputs of the graph from the survivors."""
        guards = {node: {} for node in self.kept}
        for node in self.graph.nodes:
            guards[self.survivor[node]].update(dict.fromkeys(map(self._merged, node.guards)))
        for index, node in enumerate(self.kept):
            node.index = index
            node.guards = list(guards[node])
        self.graph.nodes = self.kept
        self.graph.checks = [node for node in self.kept if node.kind == "check"]
        for code, check in enumerate(self.graph.checks, start=1):
            check.code = code
        self.graph.outputs = {
            name: self._merged(operand) for name, operand in self.graph.outputs.items()
        }
        kept = set(self.kept)
        for body in self.graph.bodies:
            body.remap(self._merged, kept)
        if self.graph.result is not None:
            self.graph.result = self.graph.result.mapped(self._merged_value)

    def _keep(self, node):
        self.survivor[node] = node
        self.kept.append(node)
        self.safe[node] = node in self.certain
        self.guarded[node] = bool(node.guards)

    def _may_merge(self, twin, node):
        """Return whether the guards of either twin may reach the consumers of the other."""
        node_ok = node in self.certain or not node.guards
        twin_ok = self.safe[twin] or not self.guarded[twin]
        return node_ok and twin_ok

    def _merged(self, operand):
        return self.survivor[operand] if isinstance(operand, Node) else operand

    def _merged_attributes(self, attributes):
        values = {name: self._merged_value(value) for name, value in attributes["values"].items()}
        return {**attributes, "values": values}

    def _merged_value(self, value):
        if isinstance(value, Proxy):
            return Proxy(self.survivor[value.node], value.graph)
        if isinstance(value, (list, tuple)):
            return type(value)(self._merged_value(item) for item in value)
        return value


def _certain_nodes(graph):
    """Return the nodes whose errors reach a graph output on every row where they fire."""
    certain = {operand for operand in graph.outputs.values() if isinstance(operand, Node)}
    for node in reversed(graph.nodes):
        if node in certain:
            operands = node.operands[:1] if node.op == "where" else node.operands
            certain.update(operand for operand in operands if isinstance(operand, Node))
    return certain


def _key(node):
    """Return the hashable identity of a node: op, operands, attributes and loop body."""
    return (
        node.op,
        tuple(map(_operand_key, node.operands)),
        _attributes_key(node.attributes),
        node.body,
    )


def _operand_key(operand):
    return ("node", operand) if isinstance(operand, Node) else _literal_key(operand)


def _attributes_key(attributes):
    if attributes is None:
        return ()
    return tuple(
        (name, _values_key(item) if name == "values" else _literal_key(item))
        for name, item in attributes.items()
    )


def _values_key(values):
    return tuple((name, _value_key(value)) for name, value in values.items())


def _value_key(value):
    if isinstance(value, Proxy):
        return ("node", value.node)
    if isinstance(value, (list, tuple)):
        return (type(value), tuple(map(_value_key, value)))
    return _literal_key(value)


def _literal_key(value):
    """Return a key equal for two literals only when they have the same type and exact value."""
    if isinstance(value, Constant):
        return (Constant, value.name)
    if isinstance(value, (float, np.floating)):
        return (type(value), struct.pack(">d", float(value)))
    try:
        hash(value)
    except TypeError:
        return (type(value), id(value))
    return (type(value), value)
