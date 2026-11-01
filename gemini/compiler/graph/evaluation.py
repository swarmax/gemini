"""``evaluate``: one evaluation of a graph over the rows of a chunk, on either backend.

``evaluate(graph, feeds, rows, context, module=...)`` is used by ``gemini.compiler.graph.run`` and
the engine. The backend is the one of ``gm.runtime.settings(backend=...)``, NumPy by default: NumPy
evaluates the graph in one pass over arrays of ``rows``; Python evaluates the same graph row by
row with Python floats and lists and stacks the nodes into the same arrays. Both go through the
same ``Interpreter`` and the same reached-code computation (``Interpreter.reached``). A root
break graph calls the real ``module`` row by row (see ``rootbreak``), and so does a break node
for its own module below ``module``: the graph holds no module, so ``module`` is the root the
graph is evaluated for, any module of the structure it was traced from. ``feeds`` maps graph
inputs to arrays over the rows or scalars, which broadcast; ``context`` may hold ``dt`` and
``states`` for a stepped root break.

An ``Evaluation`` is a ``gemini.engine.evaluation.Evaluation`` that also keeps its ``graph``.
"""

import numpy as np

from gemini.compiler.graph.failures import RowView, row_error
from gemini.compiler.graph.interpreter import Interpreter
from gemini.compiler.graph.node import Node
from gemini.compiler.graph.proxy import Proxy
from gemini.engine import evaluation
from gemini.engine.rows import run_rows, stack_column, stacked
from gemini.ops import kernels


class Evaluation(evaluation.Evaluation):
    """The result of evaluating a graph over ``rows`` rows."""

    def __init__(self, graph, rows, failed, result, errors, states=None, convert=None):
        """Keep the mapped ``result``, the ``failed`` mask and ``errors``, a function of a row."""
        super().__init__(rows, failed, result, errors, states, graph.stepped, graph.breaks)
        self.graph = graph
        self._convert = convert

    def output(self, name):
        """Return the array of the graph output ``outputs.<name>`` or ``outlets.<port>.<field>``."""
        return self._convert(self.graph.outputs[name])


def evaluate(graph, feeds, rows, context=None, module=None):
    """Evaluate ``graph`` on ``feeds`` over ``rows`` rows and return an ``Evaluation``.

    ``module`` is the root module of the call; a graph with a break node or a root break needs
    it, a graph of a plain function does not.
    """
    context = context or {}
    with np.errstate(all="ignore"):
        if graph.root_break:
            return _root_evaluation(graph, module, feeds, rows, context)
        if kernels.forced_name() == "python":
            return _python_evaluation(graph, module, feeds, rows)
        return _numpy_evaluation(graph, module, feeds, rows)


def _numpy_evaluation(graph, module, feeds, rows):
    interpreter = Interpreter(graph, kernels.get("numpy"), module)
    values, errors = interpreter.execute(feeds)
    codes = interpreter.reached(errors)

    def column(node):
        shape = (rows, *node.shape)
        return np.broadcast_to(np.asarray(values[node]), shape)

    def error(row):
        return row_error(graph.checks[int(codes[row]) - 1], RowView(values, row, feeds))

    return _assembled(graph, rows, codes, column, error)


def _python_evaluation(graph, module, feeds, rows):
    interpreter = Interpreter(graph, kernels.get("python"), module)
    row_values, row_codes = [], []
    for row in range(rows):
        values, errors = interpreter.execute(_row_feeds(graph, feeds, rows, row))
        codes = interpreter.reached(errors)
        row_values.append(values)
        row_codes.append(0 if codes is None else int(codes[0]))
    codes = np.array(row_codes, dtype=int)

    def column(node):
        return stack_column([values[node] for values in row_values])

    def error(row):
        return row_error(graph.checks[codes[row] - 1], RowView(row_values[row], 0, feeds))

    return _assembled(graph, rows, codes, column, error)


def _row_feeds(graph, feeds, rows, row):
    """Return the Python scalars of one row; a vector parameter is a Python list."""
    values = {}
    for name, value in feeds.items():
        shape = graph.inputs[name].shape
        values[name] = np.broadcast_to(np.asarray(value), (rows, *shape))[row].tolist()
    return values


def _assembled(graph, rows, codes, column, error):
    """Return the ``Evaluation`` of per-node ``column`` values and reached ``codes``."""
    failed = np.zeros(rows, dtype=bool) if codes is None else codes != 0
    convert = evaluation.converter(rows, (Node, Proxy), lambda value: column(_node(value)))
    result = None if graph.result is None else evaluation.typed(graph.result.mapped(convert))
    return Evaluation(graph, rows, failed, result, error, convert=convert)


def _root_evaluation(graph, module, feeds, rows, context):
    results, errors, states = run_rows(
        module, graph.inlet_fluids, feeds, rows, context, graph.stepped
    )
    failed = np.ones(rows, dtype=bool)
    failed[list(results)] = False
    result = stacked(results, rows)
    return Evaluation(
        graph,
        rows,
        failed,
        None if result is None else evaluation.typed(result),
        errors.__getitem__,
        states,
    )


def _node(value):
    return value.node if isinstance(value, Proxy) else value
