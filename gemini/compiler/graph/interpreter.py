"""``Interpreter``: evaluate a graph on one backend and find the errors that reach an output.

The value pass runs every node in creation order on the backend (missing ops fall back to NumPy; a
``None`` branch of ``where`` is NaN, as it is on arrays). The error pass then gives every node the
per-row error code of its operands and of the checks guarding it (of several, the lowest code,
the check that ran first, wins), except that ``where`` keeps only the
code of the branch it selected on each row. ``reached`` gives the rows whose code reaches an
output and ``evaluation.evaluate`` turns them into exceptions with ``failures.row_error``. A
break node runs its module row by row; a failed row has the code of the node's check and its
exception is re-raised.
"""

import math

import numpy as np

from gemini.compiler.graph.breaks import evaluate_break
from gemini.compiler.graph.codes import NONE
from gemini.compiler.graph.fixedpoint import evaluate_loop
from gemini.compiler.graph.node import Node
from gemini.errors import ValidationError
from gemini.ops import kernels


class Interpreter:
    """Run one graph on one backend."""

    def __init__(self, graph, backend, module=None):
        """Prepare to run ``graph`` on the backend object ``backend``, for the root ``module``."""
        self.graph = graph
        self.backend = backend
        self.module = module
        self.outer = [node for node in graph.nodes if node.body is None]
        self.seeds = {}

    def execute(self, feeds):
        """Run the value pass, then the error pass; return the node values and error codes."""
        missing = [name for name in self.graph.inputs if name not in feeds]
        if missing:
            raise ValidationError(
                f"{self.graph.module_path}: graph inputs without a value: {missing}",
                code="invalid_call",
            )
        values = {}
        self.run_nodes(self.outer, values, feeds)
        return values, self.errors_before(None, values)

    def run_nodes(self, nodes, values, feeds):
        """Evaluate ``nodes`` in order into ``values``; the carries of a body are already set."""
        for node in nodes:
            values[node] = self._evaluate(node, values, feeds)

    def reached(self, errors):
        """Return the error code reaching an output on each row, or ``None`` if none does.

        This is the one reached-code computation: the lowest code wins over all outputs.
        """
        code = _first(errors.get(operand) for operand in self.graph.outputs.values())
        if code is None:
            return None
        code = np.atleast_1d(code)
        return np.where(code == NONE, 0, code.astype(np.int64) + 1)

    def _evaluate(self, node, values, feeds):
        if node.op == "input":
            return _fed(node, feeds[node.name])
        operands = [_value(operand, values) for operand in node.operands]
        if node.op == "where":
            operands = [math.nan if operand is None else operand for operand in operands]
        if node.kind == "break":
            return _break_value(node, operands, self.module)
        if node.op == "fixed_point":
            return evaluate_loop(self, node, operands, values, feeds)
        if node.op == "loop_output":
            return operands[0].column(node.attributes["key"])
        method = kernels.implementation(self.backend, node.op)
        if node.op == "check":
            return method(operands[0], node.code)
        if node.kind == "solver":
            return method(*operands, **node.attributes)
        return method(*operands)

    def errors_before(self, node, values):
        """Return the error codes of the nodes of the level of ``node`` that precede it.

        ``node`` is a node of the outer graph or of a body; ``None`` stands for the end of the
        outer graph. Errors start at the checks, so no failing row anywhere means no codes at all.
        """
        body = None if node is None else node.body
        nodes = self.outer if body is None else body.nodes
        checks = [check for check in self.graph.checks if check.body is body]
        if node is not None:
            nodes = [other for other in nodes if other.index < node.index]
            checks = [check for check in checks if check.index < node.index]
        return self.propagate(nodes, checks, values, self.seeds.get(body, {}))

    def propagate(self, nodes, checks, values, seed):
        """Return the codes of ``nodes`` given those of ``seed`` and the failing ``checks``."""
        if not seed and not any(np.any(values[check]) for check in checks):
            return {}
        raised = {check: _raised(values[check]) for check in checks}
        errors = dict(seed)
        for node in nodes:
            if node.op == "where":
                code = _where_code(node, values, errors)
            else:
                code = _first(errors.get(operand) for operand in node.operands)
            code = _first([code] + [raised[check] for check in node.guards if check in raised])
            if code is not None and np.any(code != NONE):
                errors[node] = code
        return errors


def _fed(node, value):
    """Return the value of an input node; a parameter is a float, whatever it was given as."""
    if node.role != "parameter":
        return value
    if isinstance(value, np.ndarray):
        return value.astype(float)
    if isinstance(value, list):
        return [float(item) for item in value]
    return float(value)


def _break_value(node, operands, module):
    """Run a break node, or select one column of the result of the one it belongs to."""
    if node.op == "break":
        return evaluate_break(node, operands, module)
    return operands[0].column(node.attributes["key"])


def _value(operand, values):
    return values[operand] if isinstance(operand, Node) else operand


def _raised(values):
    """Return the codes of a check's values (``0`` for no error) as the error pass keeps them."""
    values = np.asarray(values)
    return np.where(values == 0, NONE, values - 1).astype(np.uint32)


def _first(codes):
    """Combine error codes per row: the lowest code wins and ``NONE`` is no error."""
    combined = None
    for code in codes:
        if code is None:
            continue
        combined = code if combined is None else np.minimum(combined, code)
    return combined


def _where_code(node, values, errors):
    """Return the condition's code combined with the code of the selected branch per row."""
    condition, if_true, if_false = node.operands
    branches = [errors.get(if_true), errors.get(if_false)]
    selected = None
    if any(code is not None for code in branches):
        true_code, false_code = (NONE if code is None else code for code in branches)
        selected = np.where(_value(condition, values), true_code, false_code)
    return _first([errors.get(condition), selected])
