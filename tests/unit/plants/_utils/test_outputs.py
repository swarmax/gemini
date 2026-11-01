"""Outputs of a plant: combinations of the values at paths."""

import pytest

import gemini as gm
from gemini.errors import ValidationError
from gemini.modules.declarations import Output
from gemini.plants._utils import outputs
from tests.fixtures.equivalence import assert_module_matches
from tests.fixtures.errors import raises


@pytest.fixture
def plant():
    """Return a plant with a heat exchanger and a pipe."""
    result = gm.Plant("Outputs")
    result.add("HeatExchanger", "exchanger")
    result.add("Pipe", "pipe")
    return result


def test_a_plant_declares_no_total_of_its_own(plant):
    """Without an ``outputs`` key the plant declares nothing: totals are read from ports."""
    assert list(plant.outputs(recurse=False)) == []


def test_each_form_is_a_declaration_of_paths():
    """The paths of a formula are strings, so a plant dict holds them as they are."""
    assert Output.difference("a.b", "c.d").formula == ("difference", "a.b", "c.d")
    assert Output.ratio("a.b", "c.d").formula == ("ratio", "a.b", "c.d")
    assert Output.sum("a.b", "c.d", "e.f").formula == ("sum", "a.b", "c.d", "e.f")


def test_an_output_takes_the_kind_of_its_paths(plant):
    """A difference of temperatures is a temperature difference, a ratio has no unit."""
    plant.warming = Output.difference("exchanger.hot_in.T", "exchanger.hot_out.T")
    plant.share = Output.ratio("exchanger.duty", "exchanger.duty")
    plant.total = Output.sum("exchanger.duty", "exchanger.duty")
    assert plant.warming.unit == "K" and plant.total.unit == "W"
    assert plant._output_entries["warming"] == {
        "difference": ["exchanger.hot_in.T", "exchanger.hot_out.T"]
    }


def test_an_output_waits_for_the_outputs_it_reads():
    """Bare names are earlier outputs of the plant."""
    specs = {"share": {"ratio": ["duty", "drop"]}, "duty": {"sum": ["a.b", "c.d"]}, "drop": {}}
    assert [name for name, _ in outputs.ordered(specs)][-1] == "share"


def test_bad_outputs_name_the_problem(plant):
    """A wrong key, an unknown module or output and a clash with a module are refused."""
    with raises(ValidationError, "invalid_format"):
        outputs.declare(plant, "x", {"of": "exchanger.duty"})
    with raises(ValidationError, "invalid_format"):
        outputs.declare(plant, "x", {"difference": ["exchanger.duty"]})
    with raises(ValidationError, "unknown_name"):
        outputs.declare(plant, "x", {"sum": ["exchangr.hot_in.T", "pipe.pressure_drop"]})
    with raises(ValidationError, "unknown_name") as caught:
        outputs.declare(plant, "x", {"sum": ["exchanger.dutty", "pipe.pressure_drop"]})
    assert "exchanger.duty" in caught.value.suggestions
    with pytest.raises(ValidationError):
        outputs.declare(plant, "pipe", {"sum": ["pipe.pressure_drop", "pipe.pressure_drop"]})


@pytest.mark.parametrize(
    ("key", "values", "expected"),
    [
        ("difference", [3.0, 1.0], 2.0),
        ("difference", [None, 1.0], None),
        ("ratio", [3.0, 2.0], 1.5),
        ("ratio", [3.0, 0.0], None),
        ("sum", [1.0, 2.0, 3.0], 6.0),
    ],
)
def test_the_three_forms_combine(key, values, expected):
    """A value of ``None`` or a zero divisor gives ``None``."""
    assert outputs.combine(key, values) == expected


def test_a_combination_is_traced_the_same_on_every_backend():
    """The output of a plant joins the graph and equals one eager call per row."""
    plant = gm.Plant("Held")
    plant.add("PressurizationTank", "tank")
    plant.connect("fluid_in", "tank.fluid_in")
    plant.connect("tank.fluid_out", "fluid_out")
    plant.lift = Output.difference("tank.fluid_out.p", "tank.fluid_in.p")
    plant.tank.pressure_setpoint = 2e5
    rows = [
        {
            "fluid_in": gm.Stream(
                m_dot=gm.units.Quantity(1.0, "kg/s"),
                T=gm.units.Quantity(300.0, "K"),
                p=gm.units.Quantity(value, "Pa"),
            )
        }
        for value in (1e5, 3e5)
    ]
    assert_module_matches(plant, rows)
    assert plant(**rows[0]).outputs.lift == 1e5
