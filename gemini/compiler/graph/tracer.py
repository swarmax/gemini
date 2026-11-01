"""``Tracer``: run one module call on traced values and record it as a ``Graph``.

The module is a leaf or a composite: child calls are recorded by ``Trace`` into the same graph
(see there). The trace runs ``Module._evaluate``, the one sequence of a call: ``forward``, then
(unless ``no_outputs()`` is active) the formula outputs, forward hooks and
``_check_outputs``, which runs once here; outlets of a trace are not validated. Inlet stream
fields (a ``Stream`` of traced values whose ``Fluid`` is the concrete, static one), controls,
boundaries, numeric parameters and the constants the physics uses become named graph inputs;
non-numeric and structural parameter values are trace guards (see ``cache``). A forward hook
that writes an output is part of the graph; one that only reads, and any pre-hook, is a graph
break: it is called on the module's real values, row by row.
Anything the trace cannot follow raises ``TraceError`` inside the trace; a root that cannot be
traced is never an error: ``Tracer.trace`` returns a graph with one **root break** (see
``rootbreak``) whose reason is in ``graph.breaks``. So is a root that holds a stateful module
when the run is ``stepped``: ``Module.step`` is the one implementation of a step.
"""

import numbers

from gemini import ops, runtime
from gemini._utils.strings import join_path
from gemini.compiler.graph.breaks import record_break
from gemini.compiler.graph.errors import TraceError
from gemini.compiler.graph.graph import Graph
from gemini.compiler.graph.limits import certain, check_declared_limits
from gemini.compiler.graph.node import STREAM_FIELDS
from gemini.compiler.graph.rootbreak import root_break_graph
from gemini.modules.module import _Call, _current_call, outputs_enabled
from gemini.plants._utils.plan import Solve
from gemini.types.flows import Stream
from gemini.types.ports import Ports
from gemini.types.results import ModuleResult


class Tracer:
    """Trace one call of a root module, a leaf or a composite with all its child calls."""

    def trace(self, module, fluids, stepped=False):
        """Return the graph of one call of ``module``; ``fluids`` maps inlet names to fluids.

        ``stepped`` tells that the graph is evaluated with a time step and states: a stateful
        module in the tree then makes the root a break, stepped by ``Module.step``. A root that
        cannot be traced gives a root break graph; nothing is raised for it.
        """
        module._prepare()
        reasons = _untraceable(module, stepped)
        reason = f"{module.path}: cannot be traced: {'; '.join(reasons)}" if reasons else None
        if reason is None:
            try:
                return self._traced(module, fluids)
            except TraceError as error:
                reason = str(error)
        return root_break_graph(module, fluids, stepped, reason)

    def _traced(self, module, fluids):
        graph = Graph(module.path)
        with ops.scope.tracing(graph):
            return self._record(module, graph, fluids)

    def _record(self, module, graph, fluids):
        """Record the call of ``module`` into ``graph`` and return it."""
        trace = Trace(graph, module)
        fed = {name: _inlet(graph, name, fluids[name]) for name in module._fed_inlets()}
        inlets = Ports(fed | module._empty_ports(fed), path=module.path)
        trace.limit_checks.extend(graph.checks)
        outlets, call = trace.run(module, inlets, {}, None)
        settled = module._settled_inlets(inlets, call)
        graph.result = ModuleResult.of(
            module, call.kept_outputs(), outlets, settled, call.inputs, call.call_records
        )
        for port, value in outlets.items():
            _record_outlet(graph, port, value)
        for name, value in call.kept_outputs().items():
            graph.output(f"outputs.{name}", value)
        if not graph.outputs:
            graph.result.mapped(_required(graph))
        certain(graph, trace.limit_checks + graph.unframed)
        return graph


def _required(graph):
    """Return a function that makes a value of the result tree an output of ``graph``.

    A root plant has no port, so nothing of its call reaches an output, and an error only fails a
    row when it does. Everything its leaves report then is what the run reads.
    """

    def required(value):
        graph.require(value)
        return value

    return required


class Trace:
    """The running trace of one root call; module code reaches it as ``call.trace``.

    A call made while the trace runs goes through ``child`` instead of being evaluated: the
    child's controls, boundaries and numeric parameters become graph inputs named
    ``<path relative to the root>.<name>`` (the root's own have no prefix, so a leaf keeps its
    plain names, and a child called twice reuses its inputs), its ``forward``, output step and
    forward hooks are recorded in the same fixed order as a call, and its ``ModuleResult`` holds
    traced values in the parent's call records, so the combinations of a plant and
    helper methods that call children outside ``forward`` work unchanged. A child that cannot
    be recorded raises ``TraceError``, which makes the whole root a graph break: its leaves'
    call records are read by the combinations of the parent, so a composite
    child cannot be replaced by an opaque node.
    """

    def __init__(self, graph, root):
        """Trace into ``graph``, naming inputs relative to ``root``."""
        self.graph = graph
        self.root = root
        self._inputs = {}
        self._parameters = {}
        self.limit_checks = []

    def child(self, module, inlets, supplied, parent):
        """Record one child call and return its ``ModuleResult`` of traced values.

        A stateful or pre-hooked leaf, and a leaf whose trace raises ``TraceError``, become one
        break node and the rest of the graph is kept; a composite child that cannot be
        recorded raises ``TraceError`` instead.
        """
        reasons = _untraceable(module, False)
        mark = self._mark()
        try:
            if reasons:
                raise TraceError(f"{module.path}: {reasons[0]}")
            outlets, call = self.run(module, inlets, supplied, parent)
            outputs, inputs, records = call.kept_outputs(), call.inputs, call.call_records
            settled = module._settled_inlets(inlets, call)
        except TraceError as error:
            if not module.is_leaf:
                raise
            self._rollback(mark)
            outlets, outputs, inputs, settled = record_break(
                self.graph,
                module,
                self._prefix(module),
                inlets,
                supplied,
                self._records(),
                str(error),
            )
            records = []
        result = ModuleResult.of(module, outputs, outlets, settled, inputs, records)
        if self._records():
            parent.call_records.append((module._relative_path(parent.module), result))
        return result

    def _records(self):
        """Return whether calls are recorded: those of the passes of a loop body are not."""
        return outputs_enabled() and self.graph.body is None

    def offer(self, module, inlets, parent):
        """Return the offered outlets of ``module`` on traced values; no call is recorded."""
        call = _Call(
            module=module,
            inputs=self._call_inputs(module, {}),
            outputs={},
            recording=False,
            parent=parent,
            parameters=self._call_parameters(module),
            trace=self,
        )
        token = _current_call.set(call)
        try:
            return module._offer(inlets)
        finally:
            _current_call.reset(token)

    def _mark(self):
        return self.graph.mark(), dict(self._inputs), dict(self._parameters)

    def _rollback(self, mark):
        graph_mark, self._inputs, self._parameters = mark[0], mark[1], mark[2]
        self.graph.rollback(graph_mark)

    def run(self, module, inlets, supplied, parent):
        """Trace ``forward`` and the output step of ``module``; return its outlets and call."""
        call = _Call(
            module=module,
            inputs=self._call_inputs(module, supplied),
            outputs={},
            recording=self._records(),
            parent=parent,
            parameters=self._call_parameters(module),
            trace=self,
        )
        token = _current_call.set(call)
        try:
            outlets = module._evaluate(inlets, inlets, call)
            before = len(self.graph.checks)
            check_declared_limits(module, call)
            self.limit_checks.extend(self.graph.checks[before:])
        finally:
            _current_call.reset(token)
        return outlets, call

    def _prefix(self, module):
        """Return the path of ``module`` relative to the root; empty for the root itself."""
        if module is self.root:
            return ""
        return module.path.removeprefix(self.root.path + ".")

    def _call_inputs(self, module, supplied):
        """Return controls and boundaries: supplied values win, else one graph input each."""
        prefix = self._prefix(module)
        inputs = {}
        for role, declarations in (("control", module._controls), ("boundary", module._boundaries)):
            for name, declaration in declarations.items():
                if name in supplied:
                    inputs[name] = supplied[name]
                    continue
                if (module, name) not in self._inputs:
                    full = join_path(prefix, name)
                    self._inputs[module, name] = self.graph.input(full, role, declaration.unit)
                inputs[name] = self._inputs[module, name]
        return inputs

    def _call_parameters(self, module):
        """Return traced numeric parameters by name; other values stay as they are (guards)."""
        if module not in self._parameters:
            self._parameters[module] = _parameters(self.graph, module, self._prefix(module))
        return self._parameters[module]

    def hook(self, module, hook, inlets, outlets, call):
        """Call a forward hook on traced values; it must write an output to be part of the graph."""
        before = dict(call.outputs)
        try:
            hook(module, inlets, outlets)
        except TraceError as error:
            raise TraceError(f"{module.path}: forward hook {hook!r}: {error}") from error
        if all(before.get(name) is value for name, value in call.outputs.items()):
            raise TraceError(
                f"{module.path}: forward hook {hook!r} only reads and runs on real values"
            )


def _untraceable(module, stepped):
    """Return the reasons a call of ``module`` cannot be traced, empty when it can."""
    reasons = []
    if stepped and any(member.stateful for member in module.modules()):
        reasons.append("stateful (stepped, needs scan)")
    elif module.stateful:
        reasons.append("stateful (needs scan)")
    if module._pre_hooks:
        reasons.append("has forward pre-hooks")
    if _solves(module):
        reasons.append("solves a constraint (needs scan)")
    if runtime.get_precision() != "float64":
        reasons.append("runtime precision is not float64")
    return reasons


def _solves(module):
    """Return whether a call of ``module`` solves a constraint; a loop alone is traced."""
    if not module._iterates():
        return False
    plan = getattr(module, "_compiled", None)
    return plan is None or any(isinstance(item, Solve) for item in plan().items)


def _record_outlet(graph, port, value):
    """Record the graph outputs of one outlet: the stream fields, or the power."""
    if isinstance(value, list):
        return
    if not isinstance(value, Stream):
        graph.output(f"outlets.{port}", value)
        return
    graph.outlet_fluids[port] = value.fluid
    for field, _ in STREAM_FIELDS:
        graph.output(f"outlets.{port}.{field}", getattr(value, field))


def _inlet(graph, name, fluid):
    """Return the traced stream of one inlet: graph inputs for its fields, the fixed fluid."""
    fields = {field: graph.input(f"{name}.{field}", "inlet", unit) for field, unit in STREAM_FIELDS}
    return Stream._si(fluid=fluid, **fields)


def _parameters(graph, module, prefix):
    """Return traced numeric parameters by name; other values stay as they are (guards)."""
    parameters = {}
    for name, declaration in module._parameters.items():
        value = declaration.value
        shape = traced_shape(declaration)
        if shape is None:
            parameters[name] = value
            continue
        parameters[name] = graph.input(
            join_path(prefix, name), "parameter", declaration.unit, shape
        )
    return parameters


def traced_shape(declaration):
    """Return the graph-input shape of a parameter, or ``None`` when it is a plain value.

    A structural parameter and a non-numeric one are read as plain values and are cache guards.
    """
    if declaration.structural:
        return None
    return parameter_shape(declaration.value)


def parameter_shape(value):
    """Return ``()`` for a numeric value, ``(n,)`` for a numeric vector, else ``None``."""
    if _is_number(value):
        return ()
    if isinstance(value, (list, tuple)) and value and all(_is_number(item) for item in value):
        return (len(value),)
    return None


def _is_number(value):
    return isinstance(value, numbers.Real) and not isinstance(value, bool)
