"""Interpret a parsed old project as converted module designs, bindings and boundary data."""

import csv
import io
from copy import deepcopy
from typing import Any

from pydantic import Field

from gemini._utils.mappings import set_nested
from gemini._utils.strings import join_names, join_path
from gemini._utils.time import EARLIEST, to_utc
from gemini.errors import ValidationError
from gemini.types.bindings import Binding, ConfigModel, DatedParams, ModuleBindings
from gemini.types.fluid import BRINE, Fluid

from . import tables
from .project import GeminiTags, parameter_times


class ModuleDesign(ConfigModel):
    """Converted equipment design of one plant path, used only by the legacy bridge."""

    type: str
    params: list[DatedParams] = Field(min_length=1)
    fluid: Fluid = BRINE


class LegacyDesign(ConfigModel):
    """Interpretation of an old project before it is applied to a new plant."""

    modules: dict[str, ModuleDesign]
    bindings: dict[str, ModuleBindings] = Field(default_factory=dict)
    boundary: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, Any] = Field(default_factory=dict)
    unmapped: list[str] = Field(default_factory=list)
    defaulted: list[str] = Field(default_factory=list)


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


def _data_columns(project):
    """Return the header of the project's one data CSV (every CSV but trajectory files)."""
    names = sorted(
        name for name in project._auxiliary if name.endswith(".csv") and "trajectory" not in name
    )
    if len(names) != 1:
        raise ValidationError(
            f"old project: data CSV files = {names}; expected exactly one besides trajectory files",
            code="invalid_format",
        )
    text = project._auxiliary[names[0]].decode("utf-8-sig")
    return set(next(csv.reader(io.StringIO(text, newline=""), delimiter=";"), []))


def _neighbour(project, node_id, upstream):
    """Return the node linked upstream or downstream of ``node_id`` (the last such link)."""
    for link in reversed(project.links):
        if upstream and link.target == node_id:
            return link.source
        if not upstream and link.source == node_id:
            return link.target
    return None


def _snapshot(project, node_id, index):
    return {name: param.values[index] for name, param in project.params[node_id].items()}


def _snapshot_at(project, node_id, at):
    """Return a node's latest property snapshot valid at ``at``; ``None`` is always valid."""
    times = parameter_times(project, node_id)
    eligible = [
        index
        for index, time in enumerate(times)
        if time is None or at is None or to_utc(time) <= to_utc(at)
    ]
    if not eligible:
        raise ValidationError(
            f"{project.nodes[node_id].name}: parameters.timestamps = {times}; expected one at "
            f"or before {at}",
            code="invalid_format",
        )
    return _snapshot(project, node_id, eligible[-1])


def _with_trajectory(project, properties, prefix):
    """Inline a well's trajectory file, read from the project's files, as its table."""
    filename = properties.get(f"{prefix}_trajectory_file")
    if properties.get(f"{prefix}_trajectory_table") or not filename:
        return properties
    if filename not in project._auxiliary:
        raise ValidationError(
            f"{prefix}_trajectory_file = {filename!r}; expected a file of the project folder",
            code="invalid_format",
        )
    text = project._auxiliary[filename].decode("utf-8-sig")
    return properties | {f"{prefix}_trajectory_table": tables.from_trajectory_csv(text)}


def _converted(project, node_id, kinds, properties, at):
    """Return the SI parameters of one node snapshot valid from ``at``.

    Reservoirs take their well's productivity data and production wells their ESP depth from
    the neighbour's snapshot valid at the same instant.
    """
    kind = kinds[node_id]
    if kind in ("production_reservoir", "injection_reservoir"):
        role = kind.removesuffix("_reservoir")
        well = _neighbour(project, node_id, upstream=role == "injection")
        if well is None:
            raise ValidationError(
                f"{project.nodes[node_id].name}: no linked well", code="invalid_format"
            )
        well_properties = _snapshot_at(project, well, at)
        return tables.reservoir_params_from_gemini(properties, well_properties, role)
    if kind == "production_well":
        esp = _neighbour(project, node_id, upstream=False)
        esp_properties = _snapshot_at(project, esp, at) if kinds.get(esp) == "esp" else None
        properties = _with_trajectory(project, properties, "productionwell")
        return tables.productionwell_params_from_gemini(properties, esp_property=esp_properties)
    if kind == "injection_well":
        properties = _with_trajectory(project, properties, "injectionwell")
        return tables.injectionwell_params_from_gemini(properties)
    return tables.CONVERTERS[kind](properties)


def _json_params(kind, params):
    """Validate parameters on a fresh module and return them as plain JSON values."""
    module = tables.MODULE_CLASSES[kind]()
    module._override_params(params)
    return module.state_dict()[""]["params"]


def _supplement(project, node_id, kind, columns):
    """Return the parameters the data column of ``kind`` implies, or raise without that column."""
    if kind not in tables.PARAMETER_SUPPLEMENTS:
        return {}
    column, supplement = tables.PARAMETER_SUPPLEMENTS[kind]
    if column not in columns:
        names = join_names(supplement)
        raise ValidationError(
            f"{project.nodes[node_id].name}: {names} = missing; expected the data column {column}",
            path=f"{tables.NODE_PATHS[project.nodes[node_id].name]}.{names}",
            code="missing_value",
        )
    return supplement


def _snapshots(project, node_id, kinds, columns):
    """Return one node's dated parameter snapshots, oldest first."""
    kind = kinds[node_id]
    times = parameter_times(project, node_id)
    if len(set(times)) != len(times):
        raise ValidationError(
            f"{project.nodes[node_id].name}: parameters.timestamps = {times}; expected distinct "
            "effective dates",
            code="invalid_format",
        )
    supplement = _supplement(project, node_id, kind, columns)
    snapshots = []
    for index, at in enumerate(times):
        params = _converted(project, node_id, kinds, _snapshot(project, node_id, index), at)
        snapshots.append(DatedParams(valid_from=at, params=_json_params(kind, params | supplement)))
    return sorted(snapshots, key=lambda item: item.valid_from or EARLIEST)


def _unmapped_properties(project, node_id, kind):
    name = project.nodes[node_id].name
    known = tables.PROPERTIES[kind]
    return [f"{name}.parameters.{key}" for key in project.params[node_id] if key not in known]


def _defaulted_properties(project, node_id, kind):
    name = project.nodes[node_id].name
    stated = project.params[node_id]
    return [
        f"{name}.parameters.{key} (default {value!r})"
        for key, value in tables.DEFAULTS.get(kind, {}).items()
        if key not in stated
    ]


def _bind(bindings, target, column, unit):
    """Bind ``column`` to a dotted target such as ``inlets.fluid_in.p`` or ``measured.head``."""
    section, *keys = target.split(".")
    set_nested(getattr(bindings, section), keys, Binding(column=column, unit=unit))


def _supplements(kind, bound):
    """Return the dataset channels to bind for one node as ``(target, column, unit)``."""
    supplements = list(tables.SUPPLEMENTS.get(kind, []))
    inlet_pressure = bound.inlets.get("fluid_in", {}).get("p")
    if kind == "filter" and inlet_pressure is not None:
        column = inlet_pressure.column.replace("_Pin", "_PDrop")
        supplements.append(("measured.pressure_drop", column, "bar"))
    return supplements


def _node_bindings(project, node_id, kind, columns):
    """Bind one node's measured tags and dataset supplements; also return unmapped tags."""
    name = project.nodes[node_id].name
    known = tables.TAGS.get(kind, {})
    bound, unmapped = ModuleBindings(), []
    for tag, column in project.tags.get(node_id, GeminiTags()).measured.items():
        if not column:
            continue
        if tag in known:
            target, unit = known[tag]
            _bind(bound, target, column, unit)
        elif tag not in tables.IGNORED_TAGS:
            unmapped.append(f"{name}.tagnames.measured.{tag}")
    for target, column, unit in _supplements(kind, bound):
        if column in columns:
            _bind(bound, target, column, unit)
    return bound, unmapped


def _split_risers(modules):
    """Split each production well at its buried pump into the well below and a riser above.

    NOTE(refactor): expand the buried pump into two physical well segments. The riser is an
    explicit handwritten child, preserving the previous physical segmentation.
    """
    for well_path, (_, riser_path) in tables.RISERS.items():
        below = modules[well_path]
        above = below.model_copy(deep=True)
        for snapshot in below.params:
            snapshot.params["segment"] = "below_esp"
        for snapshot in above.params:
            snapshot.params["segment"] = "above_esp"
        modules[riser_path] = above


def _project_fluid(project, kinds, modules, paths, columns):
    """Return the production reservoir's brine, with the example heat capacity if inferred.

    NOTE(refactor): retain the earlier measured bulk heat-capacity assumption whenever the data
    CSV has the columns of the example heat balance.
    """
    reservoir = next((node for node, kind in kinds.items() if kind == "production_reservoir"), None)
    if reservoir is None:
        raise ValidationError(
            "old project: no reservoir without an incoming link", code="invalid_format"
        )
    properties = _snapshot(project, reservoir, -1)
    brine = Fluid(
        density=properties.get("liquid_density") or tables.FALLBACK_LIQUID_DENSITY,
        viscosity=properties.get("liquid_viscosity") or tables.FALLBACK_LIQUID_VISCOSITY,
        salinity=properties.get("salinity", 0),
        co2_mass_fraction=properties.get("co2_mass_fraction", 0),
        gas_mass_fraction=properties.get("gas_mass_fraction", 0),
    )
    if not tables.HEAT_BALANCE_COLUMNS <= columns:
        return brine
    heat_capacity = tables.EXAMPLE_BULK_HEAT_CAPACITY / brine.density
    return Fluid.model_validate(brine.model_dump() | {"specific_heat": heat_capacity})


def _root_bindings():
    inlets = {
        port: {field: Binding(column=column, unit=unit) for field, (column, unit) in fields.items()}
        for port, fields in tables.ROOT_INLETS.items()
    }
    return ModuleBindings(inlets=inlets)


def _boundary(paths, kinds, columns, fluid):
    """Return the plant boundary: assumed stream values, scenario inputs and assumptions."""
    stream_defaults = {
        paths[node]: deepcopy(tables.STREAM_DEFAULTS[kind])
        for node, kind in kinds.items()
        if kind in tables.STREAM_DEFAULTS and columns
    }
    assumptions = [tables.ROOT_ASSUMPTION]
    if tables.HEAT_BALANCE_COLUMNS <= columns:
        assumptions = tables.HEAT_BALANCE_ASSUMPTIONS + assumptions
    return {"stream_defaults": stream_defaults, "streams": {}, "assumptions": assumptions}


def _inputs(paths, kinds, fluid):
    """Return the inputs a plant takes from the project: scenario controls and inlet streams."""
    inputs = {
        join_path(paths[node], name): value
        for node, kind in kinds.items()
        for name, value in tables.SCENARIO_INPUTS.get(kind, {}).items()
    }
    fluid_json = fluid.model_dump(mode="json")
    for port, values in tables.ROOT_DEFAULTS.items():
        for field, value in (values | {"fluid": fluid_json}).items():
            inputs[f"{port}.{field}"] = value
    return inputs


def from_legacy_design(project) -> LegacyDesign:
    """Convert every node snapshot of a parsed old project and list the fields it cannot map."""
    columns = _data_columns(project)
    paths = node_paths(project)
    kinds = node_kinds(project)
    modules, bindings, unmapped, defaulted = {}, {}, [], []
    for node_id in project.params:
        path, kind = paths[node_id], kinds[node_id]
        unmapped += _unmapped_properties(project, node_id, kind)
        defaulted += _defaulted_properties(project, node_id, kind)
        snapshots = _snapshots(project, node_id, kinds, columns)
        modules[path] = ModuleDesign(type=kind, params=snapshots)
        bound, unmapped_tags = _node_bindings(project, node_id, kind, columns)
        unmapped += unmapped_tags
        if bound.controls or bound.inlets:
            bindings[path] = bound
    _split_risers(modules)
    fluid = _project_fluid(project, kinds, modules, paths, columns)
    for item in modules.values():
        item.fluid = fluid
    bindings[""] = _root_bindings()
    return LegacyDesign(
        modules=modules,
        bindings=bindings,
        boundary=_boundary(paths, kinds, columns, fluid),
        inputs=_inputs(paths, kinds, fluid),
        unmapped=unmapped,
        defaulted=defaulted,
    )
