"""The order in which a plant runs its modules, computed from its connections.

Modules are ordered by Kahn's algorithm; ties go to the module that appears first in the
connection list, then to child order, so the sums of a composite add in the order a handwritten
``forward`` would call. A plant child that sits in a cycle of the composite graph without a cycle
between leaves is opened: its own children become steps of the parent.

A connection orders its two modules by which way the value travels, not the energy. A plain one
runs the source first. On a drawn connection the taker decides the flow, so it runs first and the
source receives what was taken. An ``offered`` outlet exists before the other modules run: its
module has one step that gives the offer and one call after everything it receives.

A cycle of steps is cut at one plain connection, its tear stream: the one from a module that gives
a first guess, else the last in the connection list. The steps of a cycle, and those between the
free value and the target of a constraint, are one item of the plan.
"""

import heapq
from collections import deque
from dataclasses import dataclass, field

from gemini._utils.strings import join_path
from gemini.errors import NotImplementedYet, ValidationError
from gemini.modules.container import ModuleDict, ModuleList
from gemini.modules.module import Module

STATE = "state"


def is_plant(module):
    """Return whether ``module`` is a plant, which wires its own children."""
    return hasattr(type(module), "_port_map")


def is_group(module):
    """Return whether ``module`` only holds children."""
    return isinstance(module, (ModuleDict, ModuleList))


def split_end(text):
    """Split ``"path.port"`` into ``(path, port)``."""
    path, _, port = text.rpartition(".")
    return path, port


def members(module, prefix=""):
    """Yield ``(path, child)`` of the modules below ``module``, looking through groups."""
    for name, child in module.named_children():
        path = join_path(prefix, name)
        if is_group(child):
            yield from members(child, path)
        else:
            yield path, child


@dataclass(frozen=True)
class Link:
    """One connection with absolute ends and the path of the plant that holds it."""

    owner: str
    source: tuple
    target: tuple
    type: str | None


def all_links(plant, owner=""):
    """Return the connections of ``plant`` and then of every plant below it, as ``Link``."""
    links = [
        Link(
            owner,
            _absolute(owner, split_end(item["source"])),
            _absolute(owner, split_end(item["target"])),
            item.get("type"),
        )
        for item in plant._connections
    ]
    for path, child in members(plant, owner):
        if is_plant(child):
            links += all_links(child, path)
    return links


def _absolute(owner, end):
    return join_path(owner, end[0]), end[1]


def port_ends(value):
    """Return the ends a plant port names: one ``(path, port)`` or a list of them."""
    return value if isinstance(value, list) else [value]


def inner_ends(module, path, side, port):
    """Return the ends of plant port ``port`` of ``module`` at ``path``, as absolute ends."""
    return [
        (join_path(path, inner), inner_port)
        for inner, inner_port in port_ends(module._port_map(side)[port])
    ]


def leaf_ends(root, end, side):
    """Follow plant ports down from ``end`` to the ports of modules that are not plants."""
    path, port = end
    module = root.get_submodule(path)
    if not is_plant(module):
        return [end]
    return [
        leaf
        for inner in inner_ends(module, path, side, port)
        for leaf in leaf_ends(root, inner, side)
    ]


def declaration(root, end, side):
    """Return the port declaration at ``end``, an outlet or an inlet by ``side``."""
    return getattr(root.get_submodule(end[0]), side)()[end[1]]


def order_of(root, source, target):
    """Return the module pairs ``(first, second)`` that one connection orders."""
    outlet, inlet = declaration(root, source, "outlets"), declaration(root, target, "inlets")
    if taken_back(outlet, inlet):
        return [(target[0], source[0])]
    return [] if offered(outlet) else [(source[0], target[0])]


def offered(outlet):
    """Return whether an outlet exists before the other modules run, as its module is set."""
    return outlet.offered and outlet.owner._offers()


def taken_back(outlet, inlet):
    """Return whether the taker decides the flow of a connection and its source receives it.

    A drawn stream inlet on a plain outlet is a plain connection: there is nothing to take back.
    """
    return outlet.drawn or inlet.gives or (inlet.drawn and offered(outlet))


def find_path(edges, start, goal):
    """Return the modules from ``start`` to ``goal`` along ``edges`` (at least one), or None."""
    successors = {}
    for source, target in edges:
        successors.setdefault(source, []).append(target)
    parents, queue = {}, deque([start])
    while queue:
        node = queue.popleft()
        for following in successors.get(node, ()):
            if following == goal:
                return _trace(parents, start, node, goal)
            if following not in parents:
                parents[following] = node
                queue.append(following)
    return None


def _trace(parents, start, node, goal):
    path = [goal, node]
    while path[-1] != start and path[-1] in parents:
        path.append(parents[path[-1]])
    return path[::-1]


def collect_nodes(module, opened, prefix=""):
    """Yield ``(path, module)`` of the steps below ``module``; opened plants give their children."""
    for path, child in members(module, prefix):
        if is_plant(child) and path in opened:
            yield from collect_nodes(child, opened, path)
        else:
            yield path, child


def node_ends(root, end, side, nodes):
    """Follow plant ports of opened plants from ``end`` until they are ports of steps."""
    if end[0] in nodes:
        return [end]
    inner = inner_ends(root.get_submodule(end[0]), end[0], side, end[1])
    return [leaf for end in inner for leaf in node_ends(root, end, side, nodes)]


def _node_ends(root, links, opened, nodes):
    return [
        (source, target)
        for link in links
        if link.type != STATE and link.owner in ({""} | opened)
        for source in node_ends(root, link.source, "outlets", nodes)
        for target in node_ends(root, link.target, "inlets", nodes)
    ]


def open_cycles(root, links):
    """Return the paths of the plant children to open so no plant sits in a false cycle."""
    opened = set()
    while True:
        nodes = dict(collect_nodes(root, opened))
        edges = [
            pair
            for source, target in _node_ends(root, links, opened, nodes)
            for pair in order_of(root, source, target)
        ]
        cyclic = {
            path
            for path, module in nodes.items()
            if is_plant(module) and find_path(edges, path, path) is not None
        }
        if not cyclic:
            return opened
        opened |= cyclic


def _topological(nodes, ordered):
    first = {}
    for index, (source, target) in enumerate(ordered):
        first.setdefault(source, index)
        first.setdefault(target, index)
    pairs = set(ordered)
    indegree = {path: 0 for path in nodes}
    successors = {path: [] for path in nodes}
    for source, target in sorted(pairs):
        indegree[target] += 1
        successors[source].append(target)
    position = {path: index for index, path in enumerate(nodes)}

    def priority(path):
        return (first.get(path, len(ordered)), position[path], path)

    ready = [priority(path) for path in nodes if indegree[path] == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        path = heapq.heappop(ready)[2]
        order.append(path)
        for following in successors[path]:
            indegree[following] -= 1
            if indegree[following] == 0:
                heapq.heappush(ready, priority(following))
    return order


@dataclass
class Step:
    """One module call: where each inlet comes from, as ``("inlet", name)`` or a step port.

    A source is ``("inlet", name)``, ``("step", path, port)`` an outlet of a call, ``("offer",
    path, port)`` an offered outlet, ``("drawn", path, port)`` the value a taker drew through its
    inlet, or ``("many", sources)``. An ``offer`` step gives the offer of its module.
    """

    path: str
    module: object
    arguments: dict
    offer: bool = False


@dataclass(frozen=True)
class Tear:
    """A connection cut to close a loop: ``index`` names its value among the sources."""

    index: int
    source: tuple
    target: tuple


@dataclass
class Loop:
    """The steps of a cycle, in order, and the connections cut to run them."""

    steps: list
    tears: list


@dataclass(frozen=True)
class PlanConstraint:
    """The free control ``by`` that brings ``target`` to ``value`` within ``bounds``.

    With ``at_least`` a target that reaches its value at the lower bound keeps that bound.
    """

    target: str
    value: str
    by: str
    bounds: object
    at_least: bool = False

    def as_dict(self):
        """Return the entry of a plant dict."""
        bounds = self.bounds if isinstance(self.bounds, str) else list(self.bounds)
        kind = "at_least" if self.at_least else "equals"
        return {"target": self.target, kind: self.value, "by": self.by, "bounds": bounds}

    def below(self, owner):
        """Return this constraint with its paths relative to the plant above ``owner``."""
        ends = (self.target, self.value, self.by)
        bounds = self.bounds
        if isinstance(bounds, str):
            bounds = join_path(owner, bounds)
        else:
            bounds = tuple(join_path(owner, b) if isinstance(b, str) else b for b in bounds)
        target, value, by = (join_path(owner, end) for end in ends)
        return PlanConstraint(target, value, by, bounds, self.at_least)


@dataclass
class Solve:
    """The steps a constraint runs, in order."""

    steps: list
    constraint: PlanConstraint


@dataclass
class Plan:
    """What to run in order, and what feeds the plant outlets and the given plant inlets."""

    items: list
    outlets: dict
    given: dict
    nodes: dict = field(default_factory=dict)
    arguments: dict = field(default_factory=dict)

    @property
    def steps(self):
        """Return every step in call order."""
        result = []
        for item in self.items:
            result += item.steps if isinstance(item, (Loop, Solve)) else [item]
        return result

    @property
    def iterates(self):
        """Return whether a loop or a constraint makes a call iterate."""
        return any(isinstance(item, (Loop, Solve)) for item in self.items)


def unconnected_port(path):
    """Return the error of a port with no connection and no plant name."""
    return ValidationError(
        f"{path}: unconnected port; connect it to a module or name a plant port",
        path=path,
        code="unconnected_port",
    )


def compile_plan(root):
    """Return the ``Plan`` of ``root``; a dangling port or a state connection cannot run."""
    for _, path, port in root._unconnected_ports():
        raise unconnected_port(join_path(path, port))
    links = all_links(root)
    if any(link.type == STATE for link in links):
        raise NotImplementedYet(
            f"{root.path}: state connections; running a loop needs a previous-step value, "
            "which lands with scan"
        )
    opened = open_cycles(root, links)
    nodes = dict(collect_nodes(root, opened))
    wiring = _Wiring(root, nodes)
    for source, target in _node_ends(root, links, opened, nodes):
        wiring.connect(source, target)
    for name, ends in root._port_map("inlets").items():
        wiring.plant_inlet(name, ends)
    return wiring.plan(root, _constraints(root, opened))


def _constraints(root, opened):
    """Return the constraints of ``root`` and of the plants it opened, with paths from the root."""
    found = list(root._constraints)
    for path in opened:
        found += [item.below(path) for item in root.get_submodule(path)._constraints]
    return found


def _gives_start(module):
    """Return whether the class of ``module`` gives the first guess of a tear stream."""
    return type(module)._loop_start is not Module._loop_start


def _reach(start, successors):
    """Return the steps reachable from ``start`` along at least one pair."""
    seen, stack = set(), list(successors.get(start, ()))
    while stack:
        name = stack.pop()
        if name not in seen:
            seen.add(name)
            stack.extend(successors.get(name, ()))
    return seen


def _successors(ordered):
    successors = {}
    for first, second in ordered:
        successors.setdefault(first, []).append(second)
    return successors


def _cycles(names, ordered):
    """Return the sets of steps that lie on a common cycle."""
    successors = _successors(ordered)
    reach = {name: _reach(name, successors) for name in names}
    groups = []
    for name in names:
        if name not in reach[name] or any(name in group for group in groups):
            continue
        groups.append({other for other in reach[name] if name in reach[other]})
    return groups


def _step_of(names, path):
    """Return the longest head of a dotted ``path`` that is a step, or ``None``."""
    while path:
        if path in names:
            return path
        path = path.rpartition(".")[0]
    return None


def _between(constraint, names, ordered):
    """Return the steps from the free value of ``constraint`` to its target and value."""
    start = _step_of(names, constraint.by)
    ends = {_step_of(names, constraint.target), _step_of(names, constraint.value)} - {None}
    if start is None or not ends:
        raise ValidationError(
            f"constrain: by = {constraint.by!r}, target = {constraint.target!r}; expected paths "
            "of modules of the plant",
            path="constraints",
            code="unknown_name",
        )
    successors = _successors(ordered)
    after = _reach(start, successors) | {start}
    return {name for name in after if name in ends or _reach(name, successors) & ends}


def _offer_key(path):
    """Return the name of the offer step of the module at ``path`` among the step names."""
    return f"{path}#offer"


class _Wiring:
    """The arguments and the order of the steps, built one connection at a time."""

    def __init__(self, root, nodes):
        """Start from the steps ``nodes``, each offering module with its offer step first."""
        self.root = root
        self.nodes = nodes
        self.arguments = {path: {} for path in nodes}
        self.offers = {}
        self.feeds = {}
        self.ordered = []
        self.given = {}
        self.plain = []

    def _add(self, end, value):
        """Give the port ``end`` the source ``value``; a ``many`` port lists its sources."""
        path, port = end
        ports = self.nodes[path]._inlets | self.nodes[path]._outlets
        if ports[port].many:
            sources = self.arguments[path].setdefault(port, ("many", []))
            sources[1].append(value)
            return
        self.arguments[path][port] = value

    def _feed_offer(self, target, value, first):
        """Pass ``value`` on to the offer of the target when the offer reads that inlet."""
        path, port = target
        if port in self.nodes[path].offer_inlets:
            self.feeds.setdefault(path, {})[port] = value
            self.ordered.append((first, _offer_key(path)))

    def connect(self, source, target):
        """Record one connection between two steps."""
        outlet, inlet = (
            declaration(self.root, source, "outlets"),
            declaration(self.root, target, "inlets"),
        )
        is_offered = offered(outlet)
        first = _offer_key(source[0]) if is_offered else source[0]
        drawn = taken_back(outlet, inlet)
        if is_offered:
            self.offers.setdefault(source[0], {})
        if not inlet.gives:
            value = ("offer" if is_offered else "step", *source)
            self._add(target, value)
            self._feed_offer(target, value, first)
        if drawn:
            self._add(source, ("drawn", *target))
            self.ordered.append((target[0], source[0]))
        if is_offered or not drawn:
            self.ordered.append((first, target[0]))
        if not is_offered and not drawn and not inlet.many:
            self.plain.append((source, target))

    def plant_inlet(self, name, ends):
        """Record one plant inlet: it feeds its ends, or, when they give it, sums them."""
        located = [
            item
            for end in port_ends(ends)
            for item in node_ends(self.root, end, "inlets", self.nodes)
        ]
        for end in located:
            if declaration(self.root, end, "inlets").gives:
                self.given.setdefault(name, []).append(end)
                continue
            self._add(end, ("inlet", name))
            self._feed_offer(end, ("inlet", name), None)

    def _cut(self, cycle, ordered, tears):
        """Cut one connection of ``cycle`` and name it a tear stream."""
        inside = [
            (source, target)
            for source, target in self.plain
            if source[0] in cycle and target[0] in cycle and (source, target) not in tears
        ]
        if not inside:
            names = ", ".join(sorted(cycle))
            raise ValidationError(
                f"{self.root.path}: the cycle of {names} has no plain connection to cut",
                path="connections",
                code="invalid_connection",
            )
        guessing = [item for item in inside if _gives_start(self.nodes[item[0][0]])]
        source, target = (guessing or inside)[-1]
        tear = Tear(len(tears), source, target)
        tears[(source, target)] = tear
        ordered.remove((source[0], target[0]))
        self.arguments[target[0]][target[1]] = ("tear", tear.index)

    def _loops(self, ordered, names):
        """Cut every cycle; return the steps of each with its tears, and the pairs that remain."""
        groups = _cycles(names, ordered)
        remaining, tears = list(ordered), {}
        while True:
            cycles = _cycles(names, remaining)
            if not cycles:
                return [
                    (group, [tear for tear in tears.values() if tear.target[0] in group])
                    for group in groups
                ], remaining
            self._cut(cycles[0], remaining, tears)

    def plan(self, root, constraints):
        """Return the ``Plan``: what to run in order, what feeds the plant outlets and inlets."""
        names = {}
        for path in self.nodes:
            if path in self.offers:
                names[_offer_key(path)] = path
                self.ordered.append((_offer_key(path), path))
            names[path] = path
        ordered = [pair for pair in self.ordered if pair[0] is not None and pair[1] in names]
        loops, ordered = self._loops(ordered, names)
        solves = [(_between(item, names, ordered), item) for item in constraints]
        items = self._items(names, ordered, loops, solves)
        outlets = {
            name: [
                item
                for end in port_ends(ends)
                for item in node_ends(self.root, end, "outlets", self.nodes)
            ]
            for name, ends in root._port_map("outlets").items()
        }
        return Plan(items, outlets, self.given, self.nodes, self.arguments)

    def _items(self, names, ordered, loops, solves):
        """Return the steps in order, each loop and constraint as one item in its place."""
        kept = [group for group, _ in loops] + [group for group, _ in solves]
        heads = {name: min(group, key=list(names).index) for group in kept for name in group}
        if len(heads) != sum(map(len, kept)):
            raise ValidationError(
                f"{self.root.path}: a step belongs to two loops or constraints; expected each in "
                "one",
                path="constraints",
                code="invalid_design",
            )
        outer = [
            (heads.get(first, first), heads.get(second, second))
            for first, second in ordered
            if heads.get(first, first) != heads.get(second, second)
        ]
        top = {name: path for name, path in names.items() if heads.get(name, name) == name}
        special = {min(group, key=list(names).index): (group, tears) for group, tears in loops}
        special |= {min(group, key=list(names).index): (group, item) for group, item in solves}
        items = []
        for name in _topological(top, outer):
            if name not in special:
                items.append(self._step(name, names[name]))
                continue
            group, detail = special[name]
            inner = [pair for pair in ordered if pair[0] in group and pair[1] in group]
            local = {step: names[step] for step in names if step in group}
            steps = [self._step(step, names[step]) for step in _topological(local, inner)]
            items.append(
                Solve(steps, detail) if isinstance(detail, PlanConstraint) else Loop(steps, detail)
            )
        return items

    def _step(self, name, path):
        if name == path:
            return Step(path, self.nodes[path], self.arguments[path])
        return Step(path, self.nodes[path], self.feeds.get(path, {}), offer=True)
