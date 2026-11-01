"""Run one module over whole time series: ``evaluate`` plus a raise.

``run(module, inlets, inputs)`` is the prototype's stand-in for the engine integration. Inlets
are ``Stream`` objects whose fields are arrays over time (validated when built);
``inputs`` maps control and boundary names to arrays or scalars, and the module's persisted
values fill the rest. Parameters and constants come from the module and the graph. It is a thin
form over ``evaluate``: the graph (a root break when the module cannot be traced, its reason in
``Run.breaks``) is evaluated on the backend you name and the first failing row raises its
exception. The row count is the longest array among the inlet fields and inputs, one without arrays.

``graph_feeds`` gives the value of every graph input; the engine uses it with ``evaluate``.

``run_function(function, *args, **fixed)`` does the same for a plain function (a physics
function, a module's helper): the numeric positional arguments become graph inputs, the
function is traced once on them, and the graph is evaluated on the arguments, so an array
argument crosses ``where`` and ``check`` like a column of a run instead of raising at its first
failing row in the function body.
"""

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from gemini import ops, runtime
from gemini.compiler.graph.cache import GraphCache
from gemini.compiler.graph.evaluation import evaluate
from gemini.compiler.graph.graph import Graph
from gemini.compiler.graph.limits import certain
from gemini.compiler.graph.node import STREAM_FIELDS
from gemini.compiler.graph.proxy import Proxy
from gemini.types.flows import Stream


@dataclass
class Run:
    """Results of one run: output and outlet-field arrays, graph breaks and the graph used."""

    outputs: dict
    outlets: dict
    breaks: list
    graph: object


def run(module, inlets, inputs=None, *, backend="numpy", cache=None):
    """Evaluate ``module`` on every row of ``inlets`` and ``inputs`` and return a ``Run``."""
    inputs = dict(inputs or {})
    rows = _row_count(inlets, inputs)
    fluids = {name: inlets[name].fluid for name in module._fed_inlets()}
    graph = (cache or GraphCache()).graph(module, fluids)
    feeds = graph_feeds(graph, module, inlets, inputs)
    with runtime.settings(backend=backend):
        evaluation = evaluate(graph, feeds, rows, module=module)
    evaluation.raise_first()
    result = evaluation.result
    outlets = {port: _fields(result.outlets[port]) for port in module._given_outlets()}
    outlets |= {port: _fields(result.inlets[port]) for port in module._drawn_inlets()}
    breaks = [reason for _, reason in graph.breaks] if graph.root_break else []
    return Run(outputs=dict(result.outputs.items()), outlets=outlets, breaks=breaks, graph=graph)


def _row_count(inlets, inputs):
    """Return the longest array among the inlet fields and inputs; one row if all are scalars."""
    sizes = [
        np.size(getattr(stream, field)) for stream in inlets.values() for field, _ in STREAM_FIELDS
    ]
    sizes += [np.size(value) for value in inputs.values()]
    return max(sizes, default=1)


def _fields(value):
    """Return the values of one port by field: the stream fields, or ``power``."""
    if isinstance(value, Stream):
        return {field: getattr(value, field) for field, _ in STREAM_FIELDS}
    return {"power": value}


def graph_feeds(graph, module, inlets, inputs):
    """Return the value of every graph input; ``inputs`` maps names to arrays or scalars.

    A control or boundary without a value (``None``, for an optional one) is NaN, like every
    value-dependent ``None`` in a graph. A parameter keeps the value it was given, so a message
    prints it as the plain path does (``2``, not ``2.0``). A root break takes only the inputs
    supplied: it reads the others from the module as any call does.
    """
    feeds = {}
    for name, stream in inlets.items():
        feeds |= {
            f"{name}.{field}": np.asarray(getattr(stream, field)) for field, _ in STREAM_FIELDS
        }
    for name in graph.by_role("control") | graph.by_role("boundary"):
        owner, local = _owner(module, name)
        if name in inputs:
            value = inputs[name]
        elif not graph.root_break:
            value = owner._input_value(local)
        else:
            continue
        feeds[name] = np.asarray(np.nan if value is None else value)
    for name in graph.by_role("parameter"):
        owner, local = _owner(module, name)
        feeds[name] = np.asarray(owner._parameter_value(local))
    for name, constant in graph.constants.items():
        feeds[name] = constant.value
    return feeds


def _owner(module, name):
    """Return the module that owns the graph input ``name`` and the input's local name."""
    path, _, local = name.rpartition(".")
    return (module.get_submodule(path) if path else module), local


def run_function(function, *args, backend="numpy", **fixed):
    """Trace ``function(*args, **fixed)`` with its numeric arguments as inputs and evaluate it.

    A float, a NumPy float or a float array among ``args`` is a graph input named
    ``arg<index>``; everything else (integers, flags, text, ``None``, lists, tuples) and every
    keyword in ``fixed`` is passed as it is, as structure. The result has the structure of
    what ``function`` returns (a number, tuple, list, dict or frozen dataclass) with arrays of
    one value per row in place of numbers. A failing ``check`` that reaches the result raises
    the class and message of the first failing row, and one in a branch ``where`` does not
    select does not.
    """
    graph = Graph(function.__name__)
    traced = [_input(graph, index, arg) for index, arg in enumerate(args)]
    with ops.scope.tracing(graph):
        result = function(*(proxy for proxy, _ in traced), **fixed)
    leaves = _leaves(result)
    for name, leaf in leaves.items():
        graph.output(name, leaf)
    certain(graph, graph.unframed)
    feeds = {
        f"arg{index}": np.asarray(arg)
        for index, (proxy, arg) in enumerate(traced)
        if isinstance(proxy, Proxy)
    }
    feeds |= {name: constant.value for name, constant in graph.constants.items()}
    rows = max([np.size(value) for value in feeds.values()], default=1)
    with runtime.settings(backend=backend):
        evaluation = evaluate(graph, feeds, rows)
    evaluation.raise_first()
    scalar = all(np.ndim(value) == 0 for value in feeds.values())
    values = {
        name: evaluation.output(name)[0] if scalar else evaluation.output(name)
        for name in graph.outputs
    }
    return _rebuilt(result, values)


def _input(graph, index, arg):
    """Return ``(traced value, argument)``; a numeric argument becomes a graph input."""
    numeric = isinstance(arg, (float, np.floating)) or (
        isinstance(arg, np.ndarray) and arg.dtype.kind == "f"
    )
    if not numeric:
        return arg, arg
    return graph.input(f"arg{index}", "control"), arg


def _leaves(result, prefix="result"):
    """Return the traced leaves of ``result`` by path name."""
    if isinstance(result, (tuple, list)):
        items = enumerate(result)
    elif isinstance(result, Mapping):
        items = result.items()
    elif dataclasses.is_dataclass(result) and not isinstance(result, type):
        items = ((field.name, getattr(result, field.name)) for field in dataclasses.fields(result))
    else:
        return {prefix: result}
    leaves = {}
    for key, item in items:
        leaves |= _leaves(item, f"{prefix}.{key}")
    return leaves


def _rebuilt(result, values, prefix="result"):
    """Return ``result`` with each leaf replaced by its evaluated value."""
    if isinstance(result, (tuple, list)):
        items = [_rebuilt(item, values, f"{prefix}.{index}") for index, item in enumerate(result)]
        return type(result)(items)
    if isinstance(result, Mapping):
        return {key: _rebuilt(item, values, f"{prefix}.{key}") for key, item in result.items()}
    if dataclasses.is_dataclass(result) and not isinstance(result, type):
        changes = {
            field.name: _rebuilt(getattr(result, field.name), values, f"{prefix}.{field.name}")
            for field in dataclasses.fields(result)
        }
        return dataclasses.replace(result, **changes)
    return values[prefix]
