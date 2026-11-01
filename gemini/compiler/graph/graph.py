"""A computation graph: ordered nodes, named inputs by role, named outputs and checks."""

import dataclasses
import numbers
from collections.abc import Mapping

import numpy as np

from gemini.compiler.graph.body import Body
from gemini.compiler.graph.errors import TraceError
from gemini.compiler.graph.node import Node, caller_source
from gemini.compiler.graph.proxy import Proxy
from gemini.ops import Constant, Failed, registry


class Graph:
    """The traced graph of one module call; nodes are kept in creation (topological) order.

    ``inputs`` maps names to input nodes, ``outputs`` maps ``outputs.<name>`` and
    ``outlets.<port>.<field>`` to the node (or literal) that computes them, ``checks`` lists the
    check nodes (their codes are their position plus one), ``constants`` the ``Constant``
    objects behind the constant inputs, ``outlet_fluids`` the fixed fluid of every outlet,
    ``breaks`` lists the children that run as plain calls, as
    ``(module path, reason)`` and ``vectors`` the length of every list-valued output.

    ``result`` is the ``ModuleResult`` tree of the trace, with children, whose values are traced
    values; an evaluation maps it to arrays. ``root_break`` marks a **root break**, a graph
    without nodes whose evaluation calls the module row by row (``inlet_fluids`` are the fluids
    of its inlets and ``stepped`` tells that it advances states with ``Module.step``).

    A graph names no module: the one it is evaluated for, which may be a copy of the module it
    was traced from, is given to ``evaluate``, and a break node holds the path of its module
    below that root. So a graph can be shared by every module of the same structure.
    """

    def __init__(self, module_path):
        """Start an empty graph for the module at ``module_path``."""
        self.module_path = module_path
        self.nodes = []
        self.inputs = {}
        self.outputs = {}
        self.checks = []
        self.constants = {}
        self.outlet_fluids = {}
        self.vectors = {}
        self.breaks = []
        self.frames = []
        self.unframed = []
        self.bodies = []
        self.body = None
        self.result = None
        self.root_break = False
        self.stepped = False
        self.inlet_fluids = {}

    def input(self, name, role, unit=None, shape=()):
        """Add a named graph input and return its traced value."""
        node = self._add(Node(len(self.nodes), "input", "input", name=name, role=role))
        node.unit, node.shape = unit, shape
        self.inputs[name] = node
        return Proxy(node, self)

    def record(self, definition, operands, attributes=None):
        """Add one op node over ``operands`` and return its traced value; checks return None."""
        lifted = tuple(self._operand(operand) for operand in operands)
        node = Node(len(self.nodes), definition.name, definition.kind, operands=lifted)
        node.attributes = attributes
        node.source = caller_source()
        node.body = self.body
        self._add(node)
        if self.body is not None:
            self.body.nodes.append(node)
        if definition.kind != "check":
            return Proxy(node, self)
        self._attach_check(node)
        return None

    def output(self, name, value):
        """Name a graph output; ``value`` is a traced value, a literal number or a list of them.

        A list or tuple is a vector output of fixed length: every item is its own output named
        ``<name>[<index>]`` and ``vectors`` keeps the length under ``name``.
        """
        if isinstance(value, (list, tuple)):
            self.vectors[name] = len(value)
            for index, item in enumerate(value):
                self.outputs[f"{name}[{index}]"] = self._operand(item)
            return
        self.outputs[name] = self._operand(value)

    def mark(self):
        """Return a position to ``rollback`` to: the counts of nodes, inputs and checks."""
        return len(self.nodes), len(self.inputs), len(self.checks)

    def rollback(self, mark):
        """Drop every node, input, constant and check added since ``mark``, and their guards."""
        nodes, inputs, checks = mark
        for name in list(self.inputs)[inputs:]:
            del self.inputs[name]
            self.constants.pop(name, None)
        del self.nodes[nodes:]
        del self.checks[checks:]
        self.unframed = [check for check in self.unframed if check.index < nodes]
        for body in self.bodies:
            body.rollback(nodes)
        for node in self.nodes:
            node.guards = [guard for guard in node.guards if guard.index < nodes]

    def by_role(self, role):
        """Return the input nodes of one role by name."""
        return {name: node for name, node in self.inputs.items() if node.role == role}

    def _add(self, node):
        self.nodes.append(node)
        return node

    def _attach_check(self, node):
        """Give the check its code and keep it for the physics function that recorded it.

        A check recorded outside any physics function is in ``unframed``: it raises at once
        when eager, so the tracer makes it certain.
        """
        self.checks.append(node)
        node.code = len(self.checks)
        if self.body is not None:
            self.body.checks.append(node)
        (self.frames[-1] if self.frames else self._unowned()).append(node)

    def _unowned(self):
        """Return the checks no function owns: those of the running body, else of the graph."""
        return self.unframed if self.body is None else self.body.unframed

    def fixed_point(self, starts, limits, settings, around):
        """Record the fixed point of a loop and return its outputs by index and ``"active"``.

        ``starts`` are the first guess of each carry and ``limits`` the two temperature limits,
        traced values or numbers. ``around(carries)`` is called once, inside the body, with one
        traced carry per start; it returns the image of every carry and the values whose errors
        stop a row. ``settings`` are kept as attributes of the node, with the body.
        """
        body = Body(self.body)
        outer = self.frames
        self.body, self.frames = body, []
        self.bodies.append(body)
        try:
            for index in range(len(starts)):
                body.carries.append(self._carry(body, index))
            images, watch = around([Proxy(node, self) for node in body.carries])
        finally:
            self.body, self.frames = body.parent, outer
        body.images = tuple(self._operand(image) for image in images)
        body.watch = tuple(dict.fromkeys([*(p.node for p in _proxies(watch)), *body.required]))
        node = self.record(
            registry.get("fixed_point"), (*starts, *limits), settings | {"body": body}
        )
        keys = [*range(len(starts)), "active"]
        return {
            key: self.record(registry.get("loop_output"), (node,), {"key": key}) for key in keys
        }

    def _carry(self, body, index):
        node = Node(len(self.nodes), "carry", "loop", attributes={"index": index})
        node.body = body
        return self._add(node)

    def open_frame(self):
        """Start collecting the checks of one physics function; return the next node index."""
        self.frames.append([])
        return len(self.nodes)

    def constant_failure(self, function, error):
        """Return the error of a check that failed on constant values, which ends the trace."""
        return TraceError(f"{function}: a check failed on constant values: {error}")

    def abandon_frame(self):
        """Drop the running frame after an error; its checks stay unframed."""
        self._unowned().extend(self.frames.pop())

    def close_frame(self, result, start):
        """Guard the traced values of ``result`` with the checks of the closing frame.

        A function whose result holds no traced value passes its checks to the enclosing frame,
        or to ``unframed`` at the root. A result node older than ``start`` (an argument returned
        unchanged) is guarded through an ``identity`` node, so other users of it stay clean.
        """
        checks = self.frames.pop()
        if not checks:
            return result
        guarded = self._guarded(result, checks, start)
        if guarded is None:
            (self.frames[-1] if self.frames else self._unowned()).extend(checks)
            return result
        return guarded[0]

    def require(self, value):
        """Make the traced values of ``value`` extra outputs: their errors now reach an output.

        In the body of a loop they are watched instead: a row whose value fails stops iterating.
        """
        for proxy in _proxies(value):
            if self.body is None:
                self.output(f"required.{len(self.outputs)}", proxy)
            else:
                self.body.required.append(proxy.node)

    def _guarded(self, value, checks, start):
        """Return ``(value with guarded proxies,)``, or ``None`` if ``value`` holds no proxy."""
        if isinstance(value, Proxy):
            return (self._guard_proxy(value, checks, start),)
        if isinstance(value, (list, tuple)):
            parts = [self._guarded(item, checks, start) for item in value]
            if all(part is None for part in parts):
                return None
            return (type(value)(p[0] if p else item for p, item in zip(parts, value)),)
        if isinstance(value, Mapping):
            parts = {key: self._guarded(item, checks, start) for key, item in value.items()}
            if all(part is None for part in parts.values()):
                return None
            return ({k: parts[k][0] if parts[k] else value[k] for k in value},)
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            return self._guarded_dataclass(value, checks, start)
        return None

    def _guarded_dataclass(self, value, checks, start):
        parts = {
            field.name: self._guarded(getattr(value, field.name), checks, start)
            for field in dataclasses.fields(value)
        }
        if all(part is None for part in parts.values()):
            return None
        changes = {name: part[0] for name, part in parts.items() if part}
        return (dataclasses.replace(value, **changes),)

    def _guard_proxy(self, proxy, checks, start):
        if proxy.node.index < start or proxy.node.op == "input":
            proxy = self.record(registry.get("identity"), (proxy,))
        proxy.node.guards.extend(check for check in checks if check not in proxy.node.guards)
        return proxy

    def _operand(self, value):
        """Return the node of a traced value or constant, or a literal unchanged.

        Literals are numbers, ``None`` (a ``where`` branch without a value) and tuples of numbers
        (the fixed table of an ``interp``); lists become tuples so graphs stay immutable.
        """
        if isinstance(value, Failed):
            raise TraceError(
                f"{self.module_path}: a check failed on constant values: {value.error}"
            )
        if isinstance(value, Proxy):
            if value.graph is not self:
                raise TraceError(f"{self.module_path}: traced value of another graph")
            return value.node
        if isinstance(value, Constant):
            return self._constant(value)
        if isinstance(value, np.ndarray) and value.ndim == 0:
            return value.item()
        if value is None or isinstance(value, (numbers.Number, np.number, np.bool_)):
            return value
        if isinstance(value, (list, tuple, np.ndarray)) and not _holds_traced(value):
            return tuple(np.asarray(value, dtype=float).tolist())
        raise TraceError(
            f"{self.module_path}: operand {value!r} of type {type(value).__name__} cannot be "
            "traced; expected a number, a traced value or a Constant"
        )

    def _constant(self, constant):
        """Return the one input node of a constant, adding it on first use."""
        if constant.name not in self.inputs:
            self.input(constant.name, "constant", constant.unit)
            self.constants[constant.name] = constant
        return self.inputs[constant.name]

    def describe(self):
        """Return a readable listing: inputs by role with units, nodes, checks and outputs."""
        lines = [f"graph of {self.module_path}", "inputs:"]
        for node in self.inputs.values():
            shape = f" shape={node.shape}" if node.shape else ""
            lines.append(f"  {node.label()} {node.role} [{node.unit or '-'}]{shape}")
        lines.append("nodes:")
        for node in self.nodes:
            if node.op != "input":
                operands = ", ".join(_describe(operand) for operand in node.operands)
                inside = "" if node.body is None else f"[loop {self.bodies.index(node.body)}] "
                lines.append(f"  {inside}%{node.index} = {node.op}({operands})  {node.source}")
        lines.append("checks:")
        for node in self.checks:
            error = node.attributes["error"].__name__
            lines.append(f"  code {node.code}: {error} at {node.source}")
        lines.append("outputs:")
        lines.extend(f"  {name} = {_describe(value)}" for name, value in self.outputs.items())
        lines.extend(f"break: {path}: {reason}" for path, reason in self.breaks)
        if self.root_break:
            lines.append(f"root break: {self.module_path} runs eagerly, row by row")
        return "\n".join(lines)


def _proxies(value):
    """Yield the traced values held in a result: a value, a sequence, a mapping or a dataclass."""
    if isinstance(value, Proxy):
        yield value
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _proxies(item)
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _proxies(item)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            yield from _proxies(getattr(value, field.name))


def _holds_traced(values):
    return any(isinstance(value, Proxy) for value in values)


def _describe(operand):
    return operand.label() if isinstance(operand, Node) else repr(operand)
