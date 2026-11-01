"""Declared bounds as graph checks: a traced call is not validated, so the graph checks them.

``check_declared_limits(module, call)`` adds one ``ops.check`` per bound (``Declaration.limits``)
of every control, boundary and output a traced call holds, each item of a list separately, with
``ValidationError`` as ``Declaration.validate`` raises on a plain call. A declared
``X | None`` lets NaN pass, which is how ``None`` is stored on arrays. Each check keeps its
``Declaration`` and the whole value among its message values (``declaration`` and ``whole``), so
an evaluation words the error of a failing row with ``declaration.validate``. ``certain`` marks the
checks of a trace on every output of its graph, so a violated bound fails the row even when the
bad value does not reach the output through the arithmetic.
"""

import operator

from gemini import ops
from gemini.errors import ValidationError

_COMPARISONS = {
    "ge": (operator.ge, ">="),
    "gt": (operator.gt, ">"),
    "le": (operator.le, "<="),
    "lt": (operator.lt, "<"),
}


def check_declared_limits(module, call):
    """Check the bounds of the controls, boundaries and outputs recorded in ``call``."""
    declarations = module._controls | module._boundaries | module._outputs
    for name, value in (call.inputs | call.kept_outputs()).items():
        declaration = declarations[name]
        if declaration.limits():
            _check_value(declaration, value)


def _check_value(declaration, value):
    items = value if isinstance(value, (list, tuple)) else [value]
    for item in items:
        if item is None:
            continue
        for limit, bound in declaration.limits().items():
            compare, relation = _COMPARISONS[limit]
            held = compare(item, bound)
            if declaration.accepts_none():
                held = ops.logical_or(ops.isnan(item), held)
            ops.check(
                held,
                ValidationError,
                "{path}: invalid {section} value {value}; expected {relation} {bound}",
                path=declaration.path,
                section=declaration.section,
                value=item,
                relation=relation,
                bound=bound,
                declaration=declaration,
                whole=value,
            )


def certain(graph, checks):
    """Guard every output of ``graph`` with ``checks``, so each reaches an output on its rows."""
    alive = set(graph.checks)
    kept = [check for check in checks if check in alive and check.body is None]
    for node in {node for node in graph.outputs.values() if hasattr(node, "guards")}:
        node.guards.extend(check for check in kept if check not in node.guards)
