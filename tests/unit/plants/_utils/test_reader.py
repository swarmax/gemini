"""Reading a spec: every problem at once, with the path into the spec."""

import copy

import pytest

import gemini as gm
from gemini.errors import ValidationError
from gemini.plants._utils import reader


@pytest.fixture
def spec():
    """Return a valid spec with a group, a nested plant, a named port and an output."""
    return {
        "format": 2,
        "name": "DoubletHeatPlant",
        "modules": {
            "degasser": {"type": "Degasser", "params": {}},
            "filters": {"type": "ModuleDict", "modules": {"hot": {"type": "Filter", "params": {}}}},
            "pipe": {"type": "Pipe", "params": {"length": {"value": 100, "unit": "ft"}}},
        },
        "connections": [{"source": "degasser.liquid_out", "target": "filters.hot.fluid_in"}],
        "inlets": {"feed": "degasser.fluid_in", "pipe_in": "pipe.fluid_in", "air": "pipe.air_in"},
        "outlets": {
            "product": "filters.hot.fluid_out",
            "gas": "degasser.gas_out",
            "pipe_out": "pipe.fluid_out",
            "pipe_loss": "pipe.loss_out",
        },
        "outputs": {"loss": {"difference": ["pipe.fluid_in.p", "pipe.fluid_out.p"]}},
        "bindings": {},
        "param_history": {},
    }


def problems_of(spec, **changes):
    """Return the problems of a copy of ``spec`` with top-level ``changes``."""
    return gm.plants.validate(copy.deepcopy(spec) | changes, on_error="record")


def wiring_problems_of(spec, **changes):
    """Return the problems of ``problems_of`` without the ports the case leaves unconnected."""
    return [item for item in problems_of(spec, **changes) if item["code"] != "unconnected_port"]


def test_an_unconnected_port_is_reported_with_its_path(spec):
    """A port no connection or plant name uses is one problem with the port path."""
    del spec["outlets"]["gas"]
    found = problems_of(spec)
    assert [(item["code"], item["path"]) for item in found] == [
        ("unconnected_port", "degasser.gas_out")
    ]
    with pytest.raises(ValidationError) as caught:
        gm.Plant.from_dict(spec)
    assert caught.value.code == "unconnected_port" and caught.value.problems == found


def test_a_valid_spec_has_no_problems(spec):
    """The base spec builds."""
    assert gm.plants.validate(spec, on_error="record") == []


def test_every_problem_is_reported_at_once_with_its_path(spec):
    """Several mistakes give several problems, none raised."""
    spec["modules"]["degasser"]["type"] = "Degaser"
    spec["modules"]["pipe"]["params"] = {
        "length": {"value": 2, "unit": "bar"},
        "lenght": 1,
        "diameter": -1,
    }
    codes = {item["path"]: item["code"] for item in gm.plants.validate(spec, on_error="record")}
    assert codes["modules.degasser.type"] == "unknown_name"
    assert codes["modules.pipe.params.length"] == "invalid_unit"
    assert codes["modules.pipe.params.lenght"] == "unknown_name"
    assert gm.plants.validate(spec, on_error="record")[0]["suggestions"][0] == "Degasser"


def test_an_out_of_bounds_value_has_its_own_code(spec):
    """A value below its minimum is ``out_of_bounds``."""
    spec["modules"]["pipe"]["params"] = {"length": -5.0}
    (item,) = gm.plants.validate(spec, on_error="record")
    assert item["code"] == "out_of_bounds" and item["path"] == "modules.pipe.params.length"


def test_wiring_rules_report_the_connection_and_the_field(spec):
    """Each wiring rule has its code and points at ``connections[i].source|target``."""
    spec["modules"]["pipe2"] = {"type": "Pipe", "params": {}}
    spec["modules"]["filter2"] = {"type": "Filter", "params": {}}
    del spec["inlets"]["pipe_in"], spec["outlets"]["pipe_out"]
    cases = {
        "unknown_name": ("pipe.fluid_out", "filter.hot.fluid_in", "target"),
        "unknown_port": ("pipe.outlt", "pipe2.fluid_in", "source"),
        "port_in_use": ("pipe.fluid_out", "filters.hot.fluid_in", "target"),
        "stream_mismatch": ("degasser.gas_out", "filter2.fluid_in", "target"),
        "invalid_connection": ("pipe", "pipe2.fluid_in", "source"),
    }
    for code, (source, target, field) in cases.items():
        extra = {"source": source, "target": target}
        found = wiring_problems_of(spec, connections=spec["connections"] + [extra])
        assert [(item["code"], item["path"]) for item in found] == [
            (code, f"connections[1].{field}")
        ], code


def test_ambiguous_ports_are_listed(spec):
    """A bare module name needs a port in a spec; an ambiguous pair is refused elsewhere."""
    spec["modules"]["splitter"] = {"type": "Splitter", "params": {}}
    spec["connections"].append({"source": "splitter", "target": "pipe.fluid_in"})
    (item,) = wiring_problems_of(spec)
    assert item["code"] == "invalid_connection"
    assert item["suggestions"] == ["splitter.branch1_out", "splitter.branch2_out"]


def test_a_failed_module_does_not_bury_the_report_in_follow_ups(spec):
    """Connections and sections naming a module that did not build are not reported again."""
    spec["modules"]["degasser"]["type"] = "Degaser"
    spec["fluids"] = {"degasser": {}}
    assert [item["path"] for item in gm.plants.validate(spec, on_error="record")] == [
        "modules.degasser.type"
    ]


def test_shape_and_format_problems(spec):
    """Unknown keys, wrong types and old files are problems, not exceptions."""
    found = problems_of(spec, modul={}, modules=[])
    assert {"modul", "modules"} <= {item["path"] for item in found}
    assert gm.plants.validate({"version": 1}, on_error="record")[0]["code"] == "old_format"
    assert gm.plants.validate([], on_error="record")[0]["code"] == "invalid_format"
    assert gm.plants.validate({"format": 2, "name": 3}, on_error="record")[0]["path"] == "name"


def test_sections_are_checked_per_path(spec):
    """Fluids, boundary, bindings and history name the module path in the problem."""
    found = problems_of(
        spec,
        fluids={"nowhere": {}},
        boundary={"pipe": []},
        bindings={"pipe": {"nothing": {"column": "c", "unit": "W"}}},
        param_history={"pipe": [{"valid_from": "2020-01-01", "params": {"lenght": 1}}]},
    )
    assert {item["path"] for item in found} == {
        "fluids.nowhere",
        "boundary.pipe",
        "bindings.pipe.nothing",
        "param_history.pipe",
    }


def test_read_raises_one_error_that_lists_every_problem(spec):
    """``from_dict`` raises a ``ValidationError`` with all messages and the first path."""
    spec["modules"]["degasser"]["type"] = "Degaser"
    spec["modules"]["pipe"]["params"] = {"lenght": 1}
    with pytest.raises(ValidationError) as caught:
        reader.from_dict(gm.Plant, spec)
    assert caught.value.path == "modules.degasser.type"
    assert "modules.pipe.params.lenght" in str(caught.value)
