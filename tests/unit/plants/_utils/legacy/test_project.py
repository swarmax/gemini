"""Small synthetic old-format parser tests."""

import json
from datetime import datetime

from gemini.data import legacy
from gemini.errors import ValidationError
from gemini.plants._utils.legacy.project import (
    GeminiLink,
    GeminiNode,
    GeminiParam,
    GeminiProject,
    GeminiTags,
)
from tests.fixtures.errors import raises


def test_project_and_csv_round_trip(tmp_path):
    """Raw old values survive JSON normalisation and semicolon CSV conversion."""
    node_id = "node-1"
    diagram = {
        "cells": [
            {
                "id": node_id,
                "type": "devs.Model",
                "properties": {"name": "pump", "type": "esp"},
                "ports": {"items": [{"id": "in"}, {"id": "out"}]},
            }
        ]
    }
    parameter = {
        "id": node_id,
        "name": "pump",
        "type": "esp",
        "parameters": {"property": {"stages": [10]}, "timestamps": ["2024-01-01"]},
        "tagnames": {
            "measured": {"flow": ["Q"]},
            "filtered": {},
            "calculated": {},
        },
    }
    (tmp_path / "diagram.json").write_text(json.dumps(diagram))
    (tmp_path / "pump.param").write_text(json.dumps(parameter))
    project = legacy.GeminiProject.from_folder(tmp_path)
    assert project.nodes[node_id].ports == ["in", "out"]
    out = tmp_path / "out"
    project.to_folder(out)
    assert legacy.GeminiProject.from_folder(out).params == project.params


def _write_project(folder, tagnames=None):
    """Write a one-node old project and return its node id."""
    folder.mkdir(parents=True, exist_ok=True)
    node_id = "node-1"
    diagram = {
        "cells": [
            {
                "id": node_id,
                "type": "devs.Model",
                "properties": {"name": "pump", "type": "esp"},
                "ports": {"items": [{"id": "in"}]},
            }
        ]
    }
    parameter = {
        "id": node_id,
        "name": "pump",
        "type": "esp",
        "parameters": {"property": {"unit": ["°C"]}, "timestamps": ["2024-01-01 00:00:00"]},
        "tagnames": tagnames or {"measured": {"flow": ["Q"]}},
    }
    (folder / "diagram.json").write_text(json.dumps(diagram), encoding="utf-8")
    (folder / "pump.param").write_text(json.dumps(parameter, ensure_ascii=False), encoding="utf-8")
    return node_id


def test_read_project_errors_name_the_file(tmp_path):
    """Malformed files and time-varying tags raise ValidationError naming the source."""
    _write_project(tmp_path / "varying", {"measured": {"flow": ["Q", "R"]}})
    with raises(ValidationError, "invalid_format", match="pump.param.*flow"):
        legacy.GeminiProject.from_folder(tmp_path / "varying")
    with raises(ValidationError, "invalid_format", match="diagram.json"):
        legacy.GeminiProject.from_folder(tmp_path / "missing")


def test_write_project_keeps_unknown_tag_kinds_and_text(tmp_path):
    """Tag kinds the typed model does not know survive a round trip, as does UTF-8 text."""
    _write_project(tmp_path / "old", {"measured": {"flow": ["Q"]}, "setpoint": {"s": ["S"]}})
    project = legacy.GeminiProject.from_folder(tmp_path / "old")
    assert project.params["node-1"]["unit"].values == ["°C"]
    project.to_folder(tmp_path / "out")
    written = json.loads((tmp_path / "out" / "pump.param").read_text(encoding="utf-8"))
    assert written["tagnames"]["setpoint"] == {"s": ["S"]}
    assert written["tagnames"]["measured"] == {"flow": ["Q"]}
    assert written["parameters"]["property"]["unit"] == ["°C"]


def test_write_project_rejects_edited_topology(tmp_path):
    """Nodes or links changed on a parsed project raise instead of being silently dropped."""
    _write_project(tmp_path / "old")
    project = legacy.GeminiProject.from_folder(tmp_path / "old")
    project.links.append(
        GeminiLink(source="node-1", source_port="in", target="node-1", target_port="in")
    )
    with raises(ValidationError, "invalid_format", match="nodes or links"):
        project.to_folder(tmp_path / "out")


def test_constructed_project_writes_new_files(tmp_path):
    """A project built in code writes a diagram and one .param file per node."""
    when = datetime(2024, 1, 1)
    project = GeminiProject(
        nodes={"a": GeminiNode(id="a", type="filter", name="filter_a", ports=["in"])},
        links=[],
        params={"a": {"clogging_dp": GeminiParam(values=[0.5], timestamps=[when])}},
        tags={"a": GeminiTags(measured={"filter_flow": "Qp"})},
    )
    project.to_folder(tmp_path / "new")
    reread = legacy.GeminiProject.from_folder(tmp_path / "new")
    assert reread.params == project.params
    assert reread.tags == project.tags
    assert reread.nodes == project.nodes
