"""``GraphCache``: traced graphs by the structure of a module, retraced only when it changes.

The key of a graph is what the trace bakes in, for every module of the tree (a change anywhere
below the root retraces): the root's path, the module class and its declaration names and output
formulas, the connections, constraints and ports of a plant, the values of non-numeric and
structural parameters and the shapes of numeric ones, the registered hooks and the module's own
fluid; and, once, whether outputs are enabled, the runtime precision, the inlet fluids and
whether the graph is ``stepped``. Numeric parameter values, constants and inputs are graph
inputs, so changing them never retraces, and a graph holds no module (see ``Graph``): every
module with the same key, a copy of a plant with other numeric values for one, shares one graph.
The cache stores graphs only: a module that cannot be traced is a root break graph (see
``rootbreak``), remembered until the structure changes. Every graph is traced once and then
merged by ``eliminate_common_subexpressions``; ``GraphCache(optimize=False)`` keeps the traced
graph as it is, for benchmarks and debugging.

``graph_cache`` gives the one cache of the process, which the compiled executor uses. It keeps at
most ``MAXSIZE`` graphs, the least recently used going first, so a long study of changing
structures does not grow it: a graph refers to the declarations of the module it was traced from,
and with them to that module, until it is dropped. A lock guards the table, so threads may share
the cache, each with its own plants; two threads that miss on one key both trace it, and the
last graph stays.
"""

import threading
from collections import OrderedDict

from gemini import runtime
from gemini.compiler.graph.passes import eliminate_common_subexpressions
from gemini.compiler.graph.tracer import Tracer, traced_shape
from gemini.modules.module import outputs_enabled

MAXSIZE = 16
"""The most graphs the cache of the process keeps."""


class GraphCache:
    """Traced graphs (or graph breaks) by structure key, the least recently used dropped."""

    def __init__(self, optimize=True, maxsize=MAXSIZE):
        """Start empty; ``traces`` counts the traces made and ``optimize`` runs the graph passes."""
        self.optimize = optimize
        self.maxsize = maxsize
        self._entries = OrderedDict()
        self._lock = threading.Lock()
        self.traces = 0

    def graph(self, module, fluids, stepped=False):
        """Return the graph of ``module`` for inlet ``fluids``; a break is a root break graph."""
        module._prepare()
        key = _guards(module, fluids, stepped)
        with self._lock:
            graph = self._entries.get(key)
            if graph is not None:
                self._entries.move_to_end(key)
                return graph
        graph = self._trace(module, fluids, stepped)
        with self._lock:
            self._entries[key] = graph
            self._entries.move_to_end(key)
            while len(self._entries) > self.maxsize:
                self._entries.popitem(last=False)
        return graph

    def clear(self):
        """Drop every graph, so the next call of each structure traces again."""
        with self._lock:
            self._entries.clear()

    def _trace(self, module, fluids, stepped):
        self.traces += 1
        graph = Tracer().trace(module, fluids, stepped)
        if self.optimize:
            eliminate_common_subexpressions(graph)
        return graph


_SHARED = GraphCache()


def graph_cache():
    """Return the one ``GraphCache`` of the process, so graphs outlive any engine and plant."""
    return _SHARED


def _guards(module, fluids, stepped):
    tree = tuple((path, _module_guards(member)) for path, member in module.named_modules())
    return (
        module.path,
        tree,
        outputs_enabled(),
        runtime.get_precision(),
        tuple(fluids[name] for name in module._fed_inlets()),
        stepped,
    )


def _module_guards(module):
    parameters = tuple(
        (name, _parameter_guard(declaration)) for name, declaration in module._parameters.items()
    )
    return (
        type(module),
        tuple((name, _formula(item)) for name, item in module._declarations().items()),
        _plant_guards(module),
        parameters,
        tuple(module._hooks.values()),
        tuple(module._pre_hooks.values()),
        module.fluid,
    )


def _parameter_guard(declaration):
    shape = traced_shape(declaration)
    if shape is None:
        return ("value", repr(declaration.value))
    return ("traced", shape)


def _formula(declaration):
    """Return the formula of an output that combines its children's values, else ``None``."""
    return getattr(declaration, "formula", None)


def _plant_guards(module):
    """Return what a plant wires: its connections, constraints and named ports; empty otherwise."""
    connections = getattr(module, "_connections", None)
    if connections is None:
        return ()
    return (
        tuple(tuple(item.items()) for item in connections),
        tuple(module._constraints),
        repr(module._listed),
    )
