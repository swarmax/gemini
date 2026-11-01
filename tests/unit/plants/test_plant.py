"""Plants built from data."""

import json

import pytest

import gemini as gm
from gemini.errors import NotImplementedYet, ValidationError
from tests.fixtures.designs import with_values
from tests.fixtures.errors import raises


@pytest.fixture
def chain():
    """Return a degasser, a filter and a second filter, wired by automatic matching."""
    plant = gm.Plant("Chain")
    plant.add("Degasser", "degasser")
    plant.add("Filter", "first")
    plant.add("Filter", "second")
    plant.connect("feed", "degasser.fluid_in")
    plant.connect("degasser", "first")
    plant.connect("first.fluid_out", "second.fluid_in")
    plant.connect("degasser.gas_out", "gas_out")
    plant.connect("second.fluid_out", "product")
    return with_values(plant)


def stream():
    """Return a brine stream."""
    return gm.Stream(
        m_dot=gm.units.Quantity(10.0, "kg/s"),
        T=gm.units.Quantity(350.0, "K"),
        p=gm.units.Quantity(5e5, "Pa"),
    )


def test_a_plant_is_a_module_in_the_plant_category():
    """A built plant is a normal composite."""
    assert isinstance(gm.Plant("doublet"), gm.modules.Module)
    assert gm.Plant.category == "plants"
    assert gm.Plant().name == "plant"


def test_names_follow_the_type_and_plant_ports_exist_only_when_named(chain):
    """Only a named port is a plant port; an added module does not add one."""
    assert list(chain.inlets()) == ["feed"]
    assert list(chain.outlets()) == ["gas_out", "product"]
    assert chain.add("Filter").name == "filter"
    assert "filter_2" not in dict(chain.named_children())
    assert chain.add("Filter") is chain.get_submodule("filter_2")
    assert list(chain.inlets()) == ["feed"]


def test_a_built_plant_runs_in_connection_order(chain):
    """The degasser feeds the filters; the plant outlets are the named outlets."""
    result = chain(feed=stream())
    assert [name for name, _ in result.call_records] == ["degasser", "first", "second"]
    assert result.outlets.gas_out.m_dot < 10.0


def test_an_unconnected_port_is_reported_with_its_path():
    """``validate`` lists every dangling port and the plant does not run."""
    plant = gm.Plant("Open")
    plant.add("Degasser", "degasser")
    plant.connect("feed", "degasser.fluid_in")
    plant.connect("degasser.liquid_out", "product")
    with_values(plant)
    found = [(item["path"], item["code"]) for item in gm.plants.validate(plant, on_error="record")]
    assert ("degasser.gas_out", "unconnected_port") in found
    with raises(ValidationError, "unconnected_port"):
        gm.plants.validate(plant)
    with raises(ValidationError, "unconnected_port") as caught:
        plant(feed=stream())
    assert caught.value.path == "degasser.gas_out"


def test_a_bare_word_names_a_plant_port(chain):
    """``connect("name", "path.port")`` names a plant inlet and is stored beside the wiring."""
    plant = gm.Plant("Named")
    plant.add("Filter", "filter")
    plant.connect("feed", "filter.fluid_in")
    plant.connect("filter.fluid_out", "product")
    spec = plant.to_dict()
    assert spec["inlets"] == {"feed": "filter.fluid_in"}
    assert spec["outlets"] == {"product": "filter.fluid_out"}
    assert spec["connections"] == []
    assert list(plant.inlets()) == ["feed"] and list(plant.outlets()) == ["product"]


def test_connection_list_gives_kind_and_type(chain):
    """The labelled end names the kind; both ends unlabelled give null."""
    assert chain._connection_list() == [
        {
            "source": "degasser.liquid_out",
            "target": "first.fluid_in",
            "kind": "brine",
            "type": None,
        },
        {"source": "first.fluid_out", "target": "second.fluid_in", "kind": "brine", "type": None},
    ]
    plant = gm.Plant("Untyped")
    plant.add("Pipe", "one")
    plant.add("Pipe", "two")
    plant.connect("one.fluid_out", "two.fluid_in", type="state")
    assert plant._connection_list() == [
        {"source": "one.fluid_out", "target": "two.fluid_in", "kind": None, "type": "state"}
    ]


def test_summary_is_a_table_with_totals(chain):
    """One row per module with type, category, inbound connections and parameter count."""
    lines = chain.summary().splitlines()
    assert lines[0] == "Plant: Chain"
    assert lines[1].split() == ["Module", "Type", "Category", "Connected", "to", "Parameters"]
    assert "fluid_in <- degasser.liquid_out" in lines[3]
    assert lines[-1].startswith("Total parameters: ")


def test_an_inlet_has_one_source_and_an_outlet_one_target(chain):
    """A second connection to a used port raises ``port_in_use``."""
    chain.add("Filter", "third")
    with pytest.raises(ValidationError) as caught:
        chain.connect("first.fluid_out", "third.fluid_in")
    assert caught.value.code == "port_in_use" and caught.value.path == "source"
    with pytest.raises(ValidationError) as caught:
        chain.connect("degasser.liquid_out", "second.fluid_in")
    assert caught.value.code == "port_in_use"


def test_ambiguous_matches_list_the_candidates():
    """Two fitting pairs raise ``ambiguous_port`` naming both."""
    plant = gm.Plant("Split")
    plant.add("Splitter", "splitter")
    plant.add("HeatExchanger", "exchanger")
    with pytest.raises(ValidationError) as caught:
        plant.connect("splitter", "exchanger")
    assert caught.value.code == "ambiguous_port"
    assert len(caught.value.suggestions) == 4
    assert "splitter.branch1_out [any] -> exchanger.hot_in [any]" in caught.value.suggestions


def test_a_stream_type_mismatch_is_refused(chain):
    """A gas outlet cannot feed a brine inlet."""
    chain.add("Degasser", "other")
    chain.add("Filter", "third")
    with pytest.raises(ValidationError) as caught:
        chain.connect("other.gas_out", "third.fluid_in")
    assert caught.value.code == "stream_mismatch"


def test_a_cycle_is_a_loop_and_a_state_connection_waits_for_scan():
    """A plain connection may close a cycle; the same wire as state does not run yet."""
    plant = gm.Plant("Loop")
    plant.add("Filter", "first")
    plant.add("Filter", "second")
    plant.connect("first.fluid_out", "second.fluid_in")
    plant.connect("second.fluid_out", "first.fluid_in")
    assert with_values(plant)._compiled().iterates
    plant = gm.Plant("Loop")
    plant.add("Filter", "first")
    plant.add("Filter", "second")
    plant.connect("first.fluid_out", "second.fluid_in")
    plant.connect("second.fluid_out", "first.fluid_in", type="state")
    with_values(plant)
    with pytest.raises(NotImplementedYet):
        plant()


def test_unknown_names_come_with_suggestions(chain):
    """Modules and ports that do not exist suggest the closest ones."""
    with raises(ValidationError, "unknown_name") as caught:
        chain.connect("frist.fluid_out", "second.fluid_in")
    assert caught.value.suggestions == ("first",)
    chain.add("Filter", "third")
    with pytest.raises(ValidationError) as caught:
        chain.connect("second.fluid_ot", "third.fluid_in")
    assert caught.value.code == "unknown_port" and caught.value.suggestions == ("fluid_out",)


def test_connections_reach_through_groups_but_never_into_plants():
    """``filters.hot.fluid_out`` is valid; ``doublet.esp.fluid_out`` is not."""
    plant = gm.Plant("Reach")
    plant.add("ModuleDict", "filters")
    plant.add("Filter", "filters.hot")
    plant.add("Filter", "filters.cold")
    plant.add("Doublet", "doublet")
    plant.connect("filters.hot.fluid_out", "filters.cold.fluid_in")
    with pytest.raises(ValidationError) as caught:
        plant.connect("doublet.esp.fluid_out", "filters.hot.fluid_in")
    assert caught.value.code == "invalid_connection"
    assert "supply_out" in str(caught.value)
    with pytest.raises(ValidationError):
        plant.connect("filters", "doublet")


def test_a_plant_child_in_a_false_cycle_is_opened():
    """The doublet loop through the surface equipment runs the doublet's children directly."""
    plant = with_values(gm.plants.get("DoubletHeatPlant"))
    paths = [step.path for step in plant._compiled().steps]
    assert [path for path in paths if path != "doublet.formation"] == [
        "doublet.reservoir",
        "doublet.well",
        "doublet.esp",
        "doublet.riser",
        "degasser",
        "filters.hot",
        "heat_exchanger",
        "filters.cold",
        "injection_pump",
        "doublet.injector",
        "doublet.sink",
    ]


def test_a_plant_child_outside_a_cycle_is_called_as_one_unit():
    """Alone, the nested doublet is a single step and a record named after it."""
    plant = gm.Plant("Nested")
    plant.add("Doublet", "doublet")
    plant.connect("return_in", "doublet.return_in")
    plant.connect("power_in", "doublet.power_in")
    plant.connect("doublet.supply_out", "supply_out")
    assert [step.path for step in plant._compiled().steps] == ["doublet"]
    assert list(plant.inlets()) == ["return_in", "power_in"]


def test_the_doublet_runs_injection_before_production():
    """Ties go to the first appearance in the connection list, as the handwritten forward."""
    plant = with_values(gm.plants.get("Doublet"))
    paths = [step.path for step in plant._compiled().steps]
    assert [path for path in paths if path != "formation"] == [
        "injector",
        "sink",
        "reservoir",
        "well",
        "esp",
        "riser",
    ]


def test_to_spec_is_json_and_validate_is_empty(chain):
    """The spec is plain JSON, rebuilds an equal plant and has no problems."""
    spec = chain.to_dict()
    assert json.loads(json.dumps(spec, allow_nan=False)) == spec
    found = gm.plants.validate(chain, on_error="record")
    assert {item["code"] for item in found} == {"root_plant_port"}
    assert [item["path"] for item in found] == [
        "inlets.feed",
        "outlets.gas_out",
        "outlets.product",
    ]
    assert gm.Plant.from_dict(spec).to_dict() == spec


def test_a_plant_has_no_run_method():
    """A plant runs through ``gm.simulate`` or ``gm.Engine``, not through a method of its own."""
    assert not hasattr(gm.Plant("Run"), "simulate")


def test_a_standalone_plant_path_is_its_snake_case_name():
    """The root path keeps the name the class-based plant had, in events and messages."""
    assert gm.Plant("DoubletHeatPlant").path == "doublet_heat_plant"
    assert with_values(gm.plants.get("DoubletHeatPlant")).path == "doublet_heat_plant"


def test_add_takes_one_dict_of_parameters_the_dict_of_set_params():
    """Unit strings and dotted names, no keyword parameters."""
    plant = gm.Plant("Params")
    pipe = plant.add("Pipe", name="pipe", params={"length": {"value": 100, "unit": "ft"}})
    assert pipe.length == pytest.approx(30.48)
    doublet = plant.add(
        "Doublet", name="d0", params={"reservoir.temperature": {"value": 87, "unit": "degC"}}
    )
    assert doublet.reservoir.temperature == pytest.approx(360.15)
    plant.set_params("pipe", {"length": {"value": 200, "unit": "ft"}})
    assert pipe.length == pytest.approx(60.96)
    with pytest.raises(TypeError, match="length"):
        plant.add("Pipe", name="other", length=5.0)
