"""Break nodes: a leaf child that cannot be traced runs as a plain call, row by row, inside a graph.

``record_break`` records one ``break`` node for the call of a stateful, pre-hooked or
untraceable leaf child. Its operands are the fields of the inlets and the supplied control and
boundary values, flattened; its attributes are the path of the module below the root of the call
(a graph holds no module) and the layout of the operands. Every output and outlet field is a
``break_output`` node of it. ``evaluate_break`` runs the module of the root it is given row by
row on the plain path (``module(**arguments)``, so a stateful module starts from its initial
states, exactly like a call outside ``Module.step``) and stacks the results. A row that raises
is NaN and fails a check guarding every output of the node: the row carries an error code like
any failed check, and ``Evaluation.raise_first`` re-raises the exception of the first failing row.

The outlet fluids are static in a trace but unknown until the module has run. The recorder
therefore probes ``forward`` once on representative concrete inlets (never the hooks), and a
row whose outlet fluid differs from the probed one counts as failed.
"""

import numpy as np

from gemini import runtime, units
from gemini.compiler.graph.errors import TraceError
from gemini.compiler.graph.node import STREAM_FIELDS
from gemini.engine.rows import row_item, row_streams, stack_column
from gemini.errors import ValidationError
from gemini.modules.module import _Call, _current_call
from gemini.ops import Symbolic, registry
from gemini.ops.registry import get
from gemini.types.flows import Stream
from gemini.types.ports import Ports

PROBE = {"m_dot": 1.0, "T": 300.0, "p": units.PA_PER_BAR}
"""Representative values of the fields of an inlet that is traced when the fluids are probed."""

PROBE_INPUT = 1.0
"""The value of a traced control or boundary that has no stored value when the fluids are probed."""

registry.register("break", "break", 0)
registry.register("break_output", "break", 1)


class BreakResult:
    """The stacked results of a break node: arrays by key, and the exception of each failed row."""

    def __init__(self, columns, ok, exceptions, scalar):
        """Keep the value arrays by key, the per-row success mask and the failures by row."""
        self.columns = columns
        self.ok = ok
        self.exceptions = exceptions
        self.scalar = scalar

    def column(self, key):
        """Return the values of one key; plain Python scalars when every operand was a scalar."""
        values = self.ok if key == ("ok",) else self.columns[key]
        return values[0].item() if self.scalar else values


def record_break(graph, module, path, inlets, supplied, call_outputs, reason):
    """Record a break node for ``module`` and return its outlets, output values and inputs.

    ``path`` is the path of ``module`` below the root of the call, empty for the root. ``inlets``
    are the traced inlets of the call, ``supplied`` the control and boundary values the caller
    passed, ``call_outputs`` whether outputs are recorded. The outlet fluids come from a probe of
    ``forward``. The returned ``Ports`` and ``dict`` hold traced values.
    """
    inputs = _probe_inputs(module, supplied)
    fluids = _probe_fluids(module, inlets, inputs)
    names = tuple(supplied)
    streams = {port: inlets[port] for port in module._fed_inlets()}
    operands = [getattr(stream, field) for stream in streams.values() for field, _ in STREAM_FIELDS]
    operands.extend(supplied[name] for name in names)
    keys = [("outlets", port, field) for port in fluids for field, _ in STREAM_FIELDS]
    keys.extend(("outlets", port) for port in _power_outlets(module))
    keys.extend(("outputs", name) for name in (module._outputs if call_outputs else ()))
    attributes = {
        "path": path,
        "inlets": tuple((port, stream.fluid) for port, stream in streams.items()),
        "names": names,
        "fluids": fluids,
        "keys": tuple(keys),
    }
    node = graph.record(get("break"), operands, attributes)
    ok = graph.record(get("break_output"), (node,), {"key": ("ok",)})
    values = {key: graph.record(get("break_output"), (node,), {"key": key}) for key in keys}
    _guard(graph, module, ok, values.values(), reason)
    outlets = {
        port: Stream._trusted(
            fluid=fluid, **{field: values["outlets", port, field] for field, _ in STREAM_FIELDS}
        )
        for port, fluid in fluids.items()
    }
    outlets |= {port: values["outlets", port] for port in _power_outlets(module)}
    outputs = {key[1]: value for key, value in values.items() if key[0] == "outputs"}
    return Ports(outlets, path=module.path), outputs, {**inputs, **supplied}, inlets


def _power_outlets(module):
    """Return the outlets of ``module`` that carry a power."""
    return [port for port, declaration in module._outlets.items() if not declaration.carries_stream]


def _guard(graph, module, ok, outputs, reason):
    """Add the check that fails a row of a break node and travels with all its outputs."""
    attributes = {
        "error": TraceError,
        "message": f"{module.path}: graph break",
        "values": {},
        "break": ok.node.operands[0],
    }
    graph.record(get("check"), (ok,), attributes)
    for output in outputs:
        output.node.guards.append(graph.checks[-1])
    graph.breaks.append((module.path, reason))


def _probe_inputs(module, supplied):
    """Return the concrete controls and boundaries of the probe.

    A supplied number is validated, a traced value or a missing one takes the stored or default
    value, else ``PROBE_INPUT``: the probe only needs a value that lets ``forward`` run.
    """
    inputs = {}
    for name, declaration in (module._controls | module._boundaries).items():
        value = supplied.get(name)
        if value is not None and not isinstance(value, Symbolic):
            inputs[name] = declaration.validate(value)
            continue
        try:
            inputs[name] = module._input_value(name)
        except ValidationError as error:
            if error.code != "missing_value":
                raise
            inputs[name] = PROBE_INPUT
    return inputs


def _probe_fluids(module, inlets, inputs):
    """Run ``forward`` once on representative inlets and return the fluid of every outlet."""
    streams = {port: Stream(**PROBE, fluid=inlets[port].fluid) for port in module._fed_inlets()}
    call = _Call(
        module=module,
        inputs=inputs,
        outputs={},
        recording=False,
        parent=None,
        states=module._call_states(None),
    )
    token = _current_call.set(call)
    try:
        returned = module.forward(Ports(streams | module._empty_ports(), path=module.path))
        module._check_outlet_names(returned)
    except Exception as error:
        raise TraceError(f"{module.path}: cannot probe the outlet fluids: {error}") from error
    finally:
        _current_call.reset(token)
    return {
        port: returned[port].fluid
        for port in module._given_outlets()
        if module._outlets[port].carries_stream
    }


def evaluate_break(node, operands, root):
    """Run the module of a break node, below ``root``, on every row; return a ``BreakResult``."""
    attributes = node.attributes
    module = root.get_submodule(attributes["path"])
    arrays = [np.asarray(operand) for operand in operands]
    scalar = all(array.ndim == 0 for array in arrays)
    rows = 1 if scalar else max(array.size for array in arrays)
    values, exceptions = {}, {}
    for row in range(rows):
        try:
            with runtime.settings(backend=None):
                values[row] = _call_row(
                    attributes, module, [row_item(array, row) for array in arrays]
                )
        except Exception as error:
            exceptions[row] = error
    columns = {
        key: stack_column([values[row][key] if row in values else None for row in range(rows)])
        for key in attributes["keys"]
    }
    ok = np.array([row in values for row in range(rows)], dtype=bool)
    return BreakResult(columns, ok, exceptions, scalar)


def _call_row(attributes, module, items):
    """Call the module with one row and return its output and outlet values by key."""
    fields = iter(items)
    arguments = row_streams(dict(attributes["inlets"]), lambda port, field: next(fields))
    arguments.update(zip(attributes["names"], fields))
    result = module(**arguments)
    values = {}
    for key in attributes["keys"]:
        values[key] = _value(result, key)
    for port, fluid in attributes["fluids"].items():
        if result.outlets[port].fluid != fluid:
            raise TraceError(f"{module.path}: outlet {port!r} fluid differs from the traced one")
    return values


def _value(result, key):
    if key[0] == "outlets" and len(key) == 2:
        return result.outlets[key[1]]
    if key[0] == "outlets":
        return getattr(result.outlets[key[1]], key[2])
    value = result.outputs[key[1]]
    return np.nan if value is None else float(value)
