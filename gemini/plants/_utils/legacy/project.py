"""Faithful raw I/O for the old GEMINI project and semicolon CSV formats.

Old files are UTF-8. Old timestamps are wall-clock times without a zone; the bridge reads them
as UTC.
"""

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from gemini._utils.files import from_json, to_json
from gemini.errors import ValidationError

OLD_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
"""Timestamp spelling of old .param files and data CSVs."""

TAG_KINDS = ("measured", "filtered", "calculated")
"""Tag sections the typed model keeps; other raw sections survive only in the raw files."""


class GeminiNode(BaseModel):
    """One old diagram model node."""

    model_config = ConfigDict(extra="forbid")
    id: str
    type: str
    name: str
    ports: list[str] = Field(default_factory=list)


class GeminiLink(BaseModel):
    """One directed old diagram connection."""

    model_config = ConfigDict(extra="forbid")
    source: str
    source_port: str
    target: str
    target_port: str


class GeminiParam(BaseModel):
    """Raw dated old property values."""

    model_config = ConfigDict(extra="forbid")
    values: list[Any]
    timestamps: list[datetime | None]


class GeminiTags(BaseModel):
    """Old tag names grouped by their source/destination kind."""

    model_config = ConfigDict(extra="forbid")
    measured: dict[str, str] = Field(default_factory=dict)
    filtered: dict[str, str] = Field(default_factory=dict)
    calculated: dict[str, str] = Field(default_factory=dict)


class GeminiProject(BaseModel):
    """Typed old project plus private raw material for lossless round trips.

    ``from_folder`` also keeps the raw diagram and .param files, every other file of the
    folder as bytes (the data CSV and trajectory files), and each node's timestamp axis, which
    the typed parameters cannot hold for a node without properties.
    """

    model_config = ConfigDict(extra="forbid")
    nodes: dict[str, GeminiNode]
    links: list[GeminiLink]
    params: dict[str, dict[str, GeminiParam]]
    tags: dict[str, GeminiTags]
    _diagram: dict | None = PrivateAttr(default=None)
    _param_files: dict[str, dict] = PrivateAttr(default_factory=dict)
    _timestamps: dict[str, list[datetime | None]] = PrivateAttr(default_factory=dict)
    _auxiliary: dict[str, bytes] = PrivateAttr(default_factory=dict)

    @classmethod
    def from_folder(cls, folder):
        """Read and validate old diagram/.param files without interpreting physical values."""
        return _from_folder(folder)

    def to_folder(self, folder):
        """Write old project files; parsed projects keep values exactly after normalisation."""
        _to_folder(self, folder)


def parameter_times(project, node_id):
    """Return the one timestamp axis shared by every property of an old node."""
    properties = project.params[node_id]
    if not properties:
        return project._timestamps.get(node_id, [None])
    timestamps = next(iter(properties.values())).timestamps
    if any(value.timestamps != timestamps for value in properties.values()):
        raise ValidationError(
            f"{node_id}: old properties require one shared timestamp axis", code="invalid_format"
        )
    return timestamps


def _from_json(path, what):
    """Read one old JSON file, naming the file in any error."""
    try:
        return from_json(path)
    except (OSError, ValueError) as exc:
        raise ValidationError(f"{path}: invalid {what}: {exc}", code="invalid_format") from exc


def _from_node(cell, path):
    properties = cell.get("properties", {})
    node_id = cell.get("id")
    try:
        return GeminiNode(
            id=node_id,
            type=properties["type"],
            name=properties["name"],
            ports=[item["id"] for item in cell.get("ports", {}).get("items", [])],
        )
    except (KeyError, TypeError) as exc:
        raise ValidationError(
            f"{path}: malformed model node {node_id!r}: {exc}", code="invalid_format"
        ) from exc


def _from_link(cell, path):
    try:
        return GeminiLink(
            source=cell["source"]["id"],
            source_port=cell["source"]["port"],
            target=cell["target"]["id"],
            target_port=cell["target"]["port"],
        )
    except KeyError as exc:
        raise ValidationError(f"{path}: malformed link field {exc}", code="invalid_format") from exc


def _from_diagram(diagram, path):
    """Return the typed model nodes by id and the links of an old diagram."""
    cells = diagram.get("cells", [])
    nodes = [_from_node(cell, path) for cell in cells if cell.get("type") == "devs.Model"]
    links = [_from_link(cell, path) for cell in cells if cell.get("type") == "devs.Link"]
    return {node.id: node for node in nodes}, links


def _from_tags(raw, path):
    """Collapse each tag's per-timestamp column list to one column ("" when unbound)."""
    tags = {}
    for kind in TAG_KINDS:
        tags[kind] = {}
        for name, values in raw.get("tagnames", {}).get(kind, {}).items():
            populated = sorted({str(value) for value in values if value})
            if len(populated) > 1:
                raise ValidationError(
                    f"{path}: tagnames.{kind}.{name} = {populated!r}; expected one column for "
                    "every timestamp",
                    code="invalid_format",
                )
            tags[kind][name] = populated[0] if populated else ""
    return GeminiTags(**tags)


def _from_param_file(raw, path):
    """Return the node id, parsed timestamps and typed properties of one .param file."""
    try:
        node_id = raw["id"]
        timestamps = raw["parameters"]["timestamps"]
        properties = raw["parameters"]["property"]
    except (KeyError, TypeError) as exc:
        raise ValidationError(
            f"{path}: malformed old parameter file: {exc}", code="invalid_format"
        ) from exc
    times = [pd.Timestamp(value).to_pydatetime() if value else None for value in timestamps]
    params = {}
    for name, values in properties.items():
        values = values if isinstance(values, list) else [values]
        if len(values) != len(times):
            raise ValidationError(
                f"{path}: parameters.property.{name} has {len(values)} values for "
                f"{len(times)} timestamps",
                code="invalid_format",
            )
        params[name] = GeminiParam(values=values, timestamps=times)
    return node_id, times, params


def _from_folder(folder):
    """Read and validate old diagram/.param files without interpreting physical values."""
    folder = Path(folder)
    diagram_path = folder / "diagram.json"
    diagram = _from_json(diagram_path, "old diagram JSON")
    nodes, links = _from_diagram(diagram, diagram_path)
    params, tags, timestamps, raw_files = {}, {}, {}, {}
    for path in sorted(folder.glob("*.param")):
        raw = _from_json(path, "old parameter file")
        node_id, times, properties = _from_param_file(raw, path)
        if node_id not in nodes:
            raise ValidationError(
                f"{path}: node id {node_id!r} is absent from diagram.json", code="invalid_format"
            )
        params[node_id], timestamps[node_id] = properties, times
        tags[node_id] = _from_tags(raw, path)
        raw_files[path.name] = raw
    if set(params) != set(nodes):
        raise ValidationError(
            f"{folder}: diagram nodes without a .param file = {sorted(set(nodes) - set(params))}",
            code="invalid_format",
        )
    project = GeminiProject(nodes=nodes, links=links, params=params, tags=tags)
    project._diagram = diagram
    project._param_files = raw_files
    project._timestamps = timestamps
    skipped = set(raw_files) | {"diagram.json"}
    for path in folder.iterdir():
        if path.is_file() and path.name not in skipped:
            project._auxiliary[path.name] = path.read_bytes()
    return project


def _format_times(timestamps):
    return [value.strftime(OLD_TIME_FORMAT) if value else None for value in timestamps]


def _tagnames(tags, count):
    """Return the raw tag sections with each column repeated for ``count`` timestamps."""
    return {
        kind: {name: [column] * count for name, column in getattr(tags, kind).items()}
        for kind in TAG_KINDS
    }


def _new_diagram(project):
    nodes = [
        {
            "id": node.id,
            "type": "devs.Model",
            "ports": {"items": [{"id": port} for port in node.ports]},
            "properties": {"name": node.name, "type": node.type},
        }
        for node in project.nodes.values()
    ]
    links = [
        {
            "id": f"link-{index}",
            "type": "devs.Link",
            "source": {"id": link.source, "port": link.source_port},
            "target": {"id": link.target, "port": link.target_port},
        }
        for index, link in enumerate(project.links)
    ]
    return {"cells": nodes + links}


def _new_param_file(project, node):
    timestamps = parameter_times(project, node.id)
    formatted = _format_times(timestamps)
    tags = _tagnames(project.tags.get(node.id, GeminiTags()), len(timestamps))
    return {
        "id": node.id,
        "name": node.name,
        "type": node.type,
        "parameters": {
            "property": {name: value.values for name, value in project.params[node.id].items()},
            "timestamps": formatted,
        },
        "tagnames": tags | {"timestamps": formatted},
    }


def _updated_param_files(project):
    """Return the raw .param files of a parsed project with its typed values written in.

    Raw tag sections the typed model does not know are kept, in their original order.
    """
    if _from_diagram(project._diagram, "diagram.json") != (project.nodes, project.links):
        raise ValidationError(
            "to_folder: nodes or links differ from the parsed diagram.json; expected "
            "the parsed topology (edit parameters and tags only)",
            code="invalid_format",
        )
    param_files = deepcopy(project._param_files)
    by_id = {raw["id"]: raw for raw in param_files.values()}
    for node_id, properties in project.params.items():
        raw = by_id[node_id]
        timestamps = parameter_times(project, node_id)
        formatted = _format_times(timestamps)
        raw["parameters"]["timestamps"] = formatted
        raw["parameters"]["property"] = {name: value.values for name, value in properties.items()}
        tags = _tagnames(project.tags.get(node_id, GeminiTags()), len(timestamps))
        raw["tagnames"] = raw.get("tagnames", {}) | tags | {"timestamps": formatted}
    return param_files


def _to_folder(project, folder):
    """Write old project files; parsed projects retain values exactly after JSON normalisation."""
    folder = Path(folder)
    if project._diagram is None:
        diagram = _new_diagram(project)
        param_files = {
            node.name + ".param": _new_param_file(project, node) for node in project.nodes.values()
        }
    else:
        diagram, param_files = project._diagram, _updated_param_files(project)
    to_json(folder / "diagram.json", diagram, indent=4)
    for name, raw in param_files.items():
        to_json(folder / name, raw, indent=4)
    for name, value in project._auxiliary.items():
        (folder / name).write_bytes(value)
