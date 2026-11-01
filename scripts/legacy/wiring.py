"""Compare the wiring of a plant with the diagram of the old example project."""

from copy import deepcopy

from gemini.errors import ValidationError
from gemini.modules._utils.wiring import trace_wiring

from . import tables


def node_kinds(project):
    """Return each node's old kind; a reservoir with an incoming link is the injection side."""
    targets = {link.target for link in project.links}
    kinds = {}
    for node_id, node in project.nodes.items():
        kinds[node_id] = node.type
        if node.type == "reservoir":
            kinds[node_id] = "injection_reservoir" if node_id in targets else "production_reservoir"
    return kinds


def node_paths(project):
    """Return the plant path of every old node; the nodes must be the example's exactly."""
    names = {node.name for node in project.nodes.values()}
    if names != tables.NODE_PATHS.keys():
        raise ValidationError(
            f"old project: unexpected nodes = {sorted(names - tables.NODE_PATHS.keys())}, "
            f"missing nodes = {sorted(tables.NODE_PATHS.keys() - names)}; expected the node "
            "table of the example project",
            code="invalid_format",
        )
    return {node_id: tables.NODE_PATHS[node.name] for node_id, node in project.nodes.items()}


def _traced_edges(plant):
    """Return the stream connections of one step of a copy of ``plant`` with assumed inputs."""
    if not plant._root_inputs():
        raise ValidationError(
            f"{plant.path}: inputs has no plant inlet stream; expected a plant filled by "
            "a plant with an inlet stream",
            code="invalid_format",
        )
    trial = deepcopy(plant)
    trial._set_inputs(tables.TRACE_CONTROLS)
    return trace_wiring(trial, trial._root_inputs())


def _endpoint(kinds, paths, node_id, port):
    """Return ``(path, port)`` of a diagram link end, or ``None`` if the bridge cannot map it."""
    ports = tables.PORTS.get(kinds.get(node_id), {})
    if node_id not in paths or port not in ports:
        return None
    return paths[node_id], ports[port]


def _expected_edges(project):
    """Return the plant connections the old diagram describes and its unmapped link ends."""
    kinds, paths = node_kinds(project), node_paths(project)
    pumps = {pump: riser for pump, riser in tables.RISERS.values()}
    expected, errors = set(), []
    for link in project.links:
        source = _endpoint(kinds, paths, link.source, link.source_port)
        target = _endpoint(kinds, paths, link.target, link.target_port)
        if source is None or target is None:
            errors.append(
                f"Unmapped old diagram endpoint: {link.source}.{link.source_port} -> "
                f"{link.target}.{link.target_port}"
            )
            continue
        if source[0] in pumps and source[1] == "fluid_out":
            expected.add((*source, pumps[source[0]], "bottom_in"))
            source = (pumps[source[0]], "wellhead_out")
        expected.add((*source, *target))
    return expected, errors


def check_wiring(plant, project):
    """Return an empty list when observed plant stream identities match the old diagram.

    One step runs on a copy of the plant with its assumed root inputs and
    ``tables.TRACE_CONTROLS``, so the caller's plant is not changed. Failures to run the step
    propagate.
    """
    traced = _traced_edges(plant)
    expected, errors = _expected_edges(project)
    errors.extend(f"Missing connection: {edge}" for edge in sorted(expected - traced))
    errors.extend(f"Unexpected connection: {edge}" for edge in sorted(traced - expected))
    return errors
