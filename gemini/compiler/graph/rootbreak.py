"""Root break: a module that cannot be traced is called for real, row by row.

``root_break_graph`` gives a graph without nodes that is marked ``root_break``. Its inputs are
the fields of the inlets and every control and boundary of the tree, named as a traced graph
names them, so ``graph_feeds`` and the engine feed it like any graph. ``evaluate`` runs it with
``gemini.engine.rows.run_rows``, which calls the module it is evaluated for on each row.
"""

from gemini.compiler.graph.graph import Graph
from gemini.compiler.graph.node import STREAM_FIELDS


def root_break_graph(module, fluids, stepped, reason):
    """Return the graph of a root break of ``module`` for the inlet ``fluids``.

    ``stepped`` is kept only when a module of the tree is stateful: otherwise ``Module.step``
    has nothing to advance and the break is a plain call.
    """
    graph = Graph(module.path)
    for port in module._fed_inlets():
        for field, unit in STREAM_FIELDS:
            graph.input(f"{port}.{field}", "inlet", unit)
    for role, declarations in (("control", module.controls()), ("boundary", module.boundaries())):
        for path, declaration in declarations.items():
            graph.input(path, role, declaration.unit)
    graph.root_break = True
    graph.stepped = stepped and any(member.stateful for member in module.modules())
    graph.inlet_fluids = {port: fluids[port] for port in module._fed_inlets()}
    graph.breaks.append((module.path, reason))
    return graph
