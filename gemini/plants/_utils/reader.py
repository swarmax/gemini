"""Read a plant dict into a plant, collecting every problem with its path in the dict."""

from copy import deepcopy

from gemini._utils import registry
from gemini._utils.strings import close_matches, did_you_mean, join_path
from gemini.errors import GeminiError, ValidationError
from gemini.errors.base import problem, reported
from gemini.modules._utils import design
from gemini.modules._utils.serialization import (
    SECTIONS,
    Report,
    format_error,
    from_params,
    from_sections,
    located,
)
from gemini.plants._utils import inputs, outputs
from gemini.plants._utils.factory import built, make_module
from gemini.plants._utils.plan import is_group, unconnected_port
from gemini.plants._utils.writer import baseline_of

TYPES = {
    "name": str,
    "type": str,
    "size": dict,
    "modules": dict,
    "connections": list,
    "inlets": dict,
    "outlets": dict,
    "outputs": dict,
    "constraints": list,
    "params": dict,
    "fluids": dict,
    "boundary": dict,
    "bindings": dict,
    "param_history": dict,
    "inputs": dict,
}
KEYS = ("format", *TYPES)


def _checked_params(module, params, report, prefix):
    """Return the ``params`` that fit, reporting each other as ``invalid_value``.

    A value the case holds is refused, naming where it lives, and so is a number with a unit that
    is no ``{"value", "unit"}``.
    """
    kept = {}
    for name, value in params.items():
        with report.guard(prefix):
            try:
                declaration = design.parameter(module, name)
            except GeminiError:
                kept[name] = value
                continue
            if declaration.case is not None:
                raise ValidationError(
                    f"{name} is not a design value of the plant; give it in the case, at "
                    f"{declaration.case}",
                    path=name,
                    code="invalid_value",
                )
            design.refuse_bare(declaration, value, name)
            kept[name] = value
    return kept


def _shape(data, report):
    """Return ``data`` without the keys that are unknown or of the wrong JSON type."""
    clean = {}
    for key, value in data.items():
        if key not in KEYS:
            error = ValidationError(
                f"unknown key {key!r}; valid: {', '.join(KEYS)}{did_you_mean(key, KEYS)}",
                path=key,
                code="invalid_format",
                suggestions=close_matches(key, KEYS),
            )
            report.items.append(located("", error))
        elif key in TYPES and not isinstance(value, TYPES[key]):
            error = ValidationError(
                f"{key} = {type(value).__name__}; expected {TYPES[key].__name__}",
                path=key,
                code="invalid_format",
            )
            report.items.append(located("", error))
        else:
            clean[key] = value
    return clean


def _entry(plant, prefix, name, entry, report, path):
    with report.guard(path):
        if not isinstance(entry, dict) or not isinstance(entry.get("type"), str):
            raise ValidationError(
                f"{name}: expected {{type, params}}", path="type", code="invalid_format"
            )
        key = join_path(prefix, name)
        try:
            module, _ = make_module(entry["type"], entry.get("size"))
        except GeminiError:
            report.broken.add(key)
            raise
        if is_group(module):
            plant._attach(key, module, None, {})
            for child, item in entry.get("modules", {}).items():
                _entry(plant, key, child, item, report, f"{path}.modules.{child}")
            return
        baseline = baseline_of(module)
        params = _checked_params(module, entry.get("params", {}), report, f"{path}.params")
        from_params(module, params, report, f"{path}.params")
        plant._attach(key, module, deepcopy(entry.get("params")), baseline)


def _connection(plant, item, report):
    if not isinstance(item, dict) or not all(
        isinstance(item.get(k), str) for k in ("source", "target")
    ):
        raise ValidationError("expected {source, target, type?}", path="", code="invalid_format")
    usable = [end for end in ("source", "target") if not report.skips(item[end])]
    if len(usable) == 2:
        plant._link(item["source"], item["target"], item.get("type"), explicit=True)
        return
    for end in usable:
        plant._candidates(item[end], end, explicit=True)


def _port(plant, side, name, ends, report):
    """Name one plant port; several ends share a power port or the air."""
    for end in ends if isinstance(ends, list) else [ends]:
        if not isinstance(end, str):
            raise ValidationError(f"{name}: expected 'path.port'", code="invalid_format")
        if report.skips(end):
            continue
        if side == "inlets":
            plant._link(name, end, None, explicit=True)
        else:
            plant._link(end, name, None, explicit=True)


def _outputs(plant, entries, report):
    plant._output_entries = {}
    for name, data in outputs.ordered(entries):
        with report.guard(f"outputs.{name}"):
            if not isinstance(data, dict):
                raise ValidationError(f"{name}: expected a mapping", code="invalid_format")
            key, paths = outputs.check(name, data)
            if any(report.skips(path) for path in paths):
                continue
            plant._register_declaration(name, outputs.declare(plant, name, data))


def _ends(data):
    """Return every port the dict names, also those of an entry that failed to read."""
    connections = [item for item in data.get("connections", []) if isinstance(item, dict)]
    ends = {item.get(end) for item in connections for end in ("source", "target")}
    for side in ("inlets", "outlets"):
        for named in data.get(side, {}).values():
            ends |= set(named) if isinstance(named, list) else {named}
    return ends


def _check_ports(plant, data, report):
    """Report each port no entry of ``data`` names; a named port that failed has its problem."""
    named = _ends(data)
    for _, path, port in plant._unconnected_ports():
        end = join_path(path, port)
        if end not in named and not report.skips(end):
            with report.guard(""):
                raise unconnected_port(end)


def root_problems(data):
    """Return a problem for each plant port of a root plant.

    Every edge of a root plant is a module, so it has no plant ports. A registered plant is a
    building block for other plants: its ports are its interface.
    """
    if not isinstance(data, dict) or data.get("name") in registry.names():
        return []
    return [
        problem(
            f"{side}.{name}",
            "root_plant_port",
            f"{name}: a root plant has no plant ports; connect it to a module of the grids or "
            "the environment",
        )
        for side in ("inlets", "outlets")
        for name in data.get(side, {})
    ]


def _from_inputs(plant, data, report):
    """Set the ``inputs`` of ``data``, each path its own problem."""
    for path, value in data.get("inputs", {}).items():
        if report.skips(path):
            continue
        with report.guard("inputs"):
            inputs.refuse_bare(plant, path, value)
            plant.set_inputs({path: value})


def populate(plant, data, report):
    """Add the modules, connections, ports, outputs and sections of ``data`` to ``plant``."""
    for name, entry in data.get("modules", {}).items():
        _entry(plant, "", name, entry, report, f"modules.{name}")
    for index, item in enumerate(data.get("connections", [])):
        with report.guard(f"connections[{index}]"):
            _connection(plant, item, report)
    for side in ("inlets", "outlets"):
        for name, end in data.get(side, {}).items():
            with report.guard(f"{side}.{name}"):
                _port(plant, side, name, end, report)
    _check_ports(plant, data, report)
    if "outputs" in data:
        _outputs(plant, data["outputs"], report)
    for index, item in enumerate(data.get("constraints", [])):
        with report.guard(f"constraints[{index}]"):
            plant.constrain(**item)
    from_sections(plant, data, report)
    _from_inputs(plant, data, report)
    plant._sections = {key: deepcopy(data.get(key, {})) for key in SECTIONS}


def _of_class(cls, data, report):
    """Return the plant of a class: ``data`` names it and holds its size and its values."""
    with report.guard("type"):
        found = cls if cls.__name__ == data["type"] else registry.get(data["type"])
        if found is not cls and registry.category(data["type"]) != "plants":
            raise ValidationError(
                f"type = {data['type']!r}; expected a plant class: wrap a module in a plant",
                code="invalid_value",
            )
        plant = built(found, data.get("size"))
        params = _checked_params(plant, data.get("params", {}), report, "params")
        from_params(plant, params, report)
        from_sections(plant, data, report)
        _from_inputs(plant, data, report)
        plant._sections = {key: deepcopy(data.get(key, {})) for key in SECTIONS}
        return plant
    return None


def build(cls, data):
    """Return ``(plant or None, problems)`` of a plant dict; problems are empty when it is valid."""
    report = Report()
    error = format_error(data)
    if error is not None:
        report.items.append(located("", error))
        return None, report.items
    data = _shape(data, report)
    if "type" in data:
        plant = _of_class(cls, data, report)
    else:
        plant = cls._empty(data.get("name", "plant"))
        populate(plant, data, report)
    return plant, report.items


def problems(cls, data):
    """Return every problem of ``data`` as ``[{path, code, message, suggestions}]``."""
    return build(cls, data)[1]


def from_dict(cls, data):
    """Return the plant of ``data``, or raise a ``ValidationError`` that carries every problem."""
    error = format_error(data)
    if error is not None:
        raise error
    plant, items = build(cls, data)
    reported(items, "raise")
    return plant
