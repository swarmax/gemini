"""Dated parameters and bindings of a module tree."""

import pytest

import gemini as gm
from gemini.errors import ValidationError
from gemini.modules._utils import design
from tests.fixtures.errors import raises


@pytest.fixture
def exchanger():
    """Return a heat exchanger with a design."""
    return gm.modules.HeatExchanger().set_params(
        "",
        {
            "thermal_conductance": gm.units.Quantity(1e3, "W/K"),
            "hot_nominal_pressure_drop": gm.units.Quantity(1e4, "Pa"),
            "cold_nominal_pressure_drop": gm.units.Quantity(1e4, "Pa"),
        },
    )


def test_an_undated_set_changes_the_base_and_the_current_value(exchanger):
    """Unit strings are converted, and the value is in force at once."""
    exchanger.set_params("", {"hot_nominal_pressure_drop": {"value": 2, "unit": "bar"}})
    assert exchanger.hot_nominal_pressure_drop == 2e5
    assert exchanger.params_at("")["hot_nominal_pressure_drop"] == 2e5
    history = exchanger.param_history("")
    assert len(history) == 1 and history[0]["valid_from"] is None
    assert history[0]["params"]["hot_nominal_pressure_drop"] == 2e5


def test_a_dated_snapshot_is_complete_and_sorted(exchanger):
    """Each snapshot holds the values in force merged with the change."""
    exchanger.set_params(
        "", {"thermal_conductance": gm.units.Quantity(5.0, "W/K")}, valid_from="2021-01-01"
    )
    exchanger.set_params(
        "", {"thermal_conductance": gm.units.Quantity(3.0, "W/K")}, valid_from="2020-01-01"
    )
    history = exchanger.param_history("")
    assert [item["valid_from"] for item in history] == [
        None,
        "2020-01-01T00:00:00Z",
        "2021-01-01T00:00:00Z",
    ]
    assert history[2]["params"].keys() == history[0]["params"].keys()
    assert exchanger.params_at("", "2020-06-01")["thermal_conductance"] == 3.0
    assert exchanger.params_at("")["thermal_conductance"] == 5.0


def test_an_unknown_parameter_suggests_a_name(exchanger):
    """The error names the closest parameter."""
    with raises(ValidationError, "unknown_name") as caught:
        exchanger.set_params("", {"thermal_conductanc": 1.0})
    assert caught.value.suggestions == ("thermal_conductance",)


def test_bindable_lists_what_a_module_accepts(exchanger):
    """Controls, boundaries, inlet fields, measured outputs and states by name."""
    bindable = exchanger.bindable("")
    assert bindable["inlets"]["hot_in"] == ["m_dot", "T", "p"]
    assert "duty" in bindable["measured"]
    assert set(bindable) == {"controls", "boundaries", "inlets", "measured", "state"}


def test_bindings_check_units_against_the_declaration(exchanger):
    """A column in a unit of another dimension is refused; a fitting one is stored."""
    with raises(ValidationError, "invalid_unit"):
        exchanger.set_bindings("", {"duty": {"column": "d", "unit": "bar"}})
    exchanger.set_bindings("", {"duty": {"column": "d", "unit": "kW"}})
    assert exchanger.bindings[""].measured["duty"].unit == "kW"
    exchanger.set_bindings("", {})
    assert exchanger.bindings == {}


def test_bindings_reject_unknown_names_and_fields(exchanger):
    """Names and inlet fields are checked."""
    with raises(ValidationError, "unknown_name"):
        exchanger.set_bindings("", {"dutty": {"column": "d", "unit": "kW"}})
    with raises(ValidationError, "unknown_name"):
        exchanger.set_bindings("", {"hot_in.q": {"column": "d", "unit": "K"}})
    with raises(ValidationError, "invalid_binding"):
        exchanger.set_bindings("", {"duty": {"column": "d"}})


def test_a_key_is_a_declaration_name_and_a_value_a_column(exchanger):
    """A name finds its section; a column alone has the declaration's SI unit."""
    exchanger.set_bindings("", {"duty": "q", "hot_in.m_dot": {"column": "flow", "unit": "m3/h"}})
    bound = exchanger.bindings[""]
    assert bound.measured["duty"].column == "q" and bound.measured["duty"].unit == "W"
    assert bound.inlets["hot_in"]["m_dot"].unit == "m3/h"


def test_each_kind_of_declaration_binds_by_its_name():
    """Controls, boundaries, outputs, states and inlet fields need no section."""
    tank = gm.modules.ThermalStorage()
    control = next(iter(tank._controls), None)
    state = next(iter(tank._states))
    output = next(iter(tank._outputs))
    port = next(iter(tank._inlets))
    keys = [key for key in (control, state, output, f"{port}.T") if key]
    tank.set_bindings("", {key: f"column_{index}" for index, key in enumerate(keys)})
    bound = tank.bindings[""]
    assert state in bound.state and output in bound.measured and "T" in bound.inlets[port]


def test_the_section_form_is_refused(exchanger):
    """Only the flat form is read: the old key is an unknown name, and says what is valid."""
    with raises(ValidationError, "unknown_name", match="unknown name 'measured'.*duty") as caught:
        exchanger.set_bindings("", {"measured": {"duty": "d"}})
    assert caught.value.path == "measured"


def test_a_name_declared_twice_raises_and_names_the_clash(exchanger):
    """No shipped module has one; the resolver refuses to guess."""
    exchanger._controls["duty"] = exchanger._outputs["duty"]
    with raises(ValidationError, "invalid_binding", match="'duty' is declared as controls and"):
        exchanger.set_bindings("", {"duty": "d"})
    del exchanger._controls["duty"]


def test_bindings_are_not_a_list(exchanger):
    """Anything but a mapping is refused."""
    with raises(ValidationError, "invalid_binding"):
        exchanger.set_bindings("", ["duty"])


def test_flat_writes_the_column_alone_when_the_unit_is_the_declared_one(exchanger):
    """A file stays readable; a column in another unit keeps it."""
    bound = design.sectioned(
        exchanger, {"duty": "q", "effectiveness": "e", "hot_in.T": {"column": "t", "unit": "degC"}}
    )
    assert design.flat(exchanger, bound) == {
        "duty": "q",
        "effectiveness": "e",
        "hot_in.T": {"column": "t", "unit": "degC"},
    }
    assert design.flat(None, bound)["duty"] == {"column": "q", "unit": "W"}


def test_a_volume_flow_column_fits_a_mass_flow_inlet_field():
    """Inlet flow columns may be volumetric; the engine converts them."""
    assert design.FIELD_UNITS["m_dot"] == ("kg/s", "m3/s")
