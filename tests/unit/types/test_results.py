"""Recorded call values, unit conversion on access and module result trees."""

import numpy as np
import pytest

from gemini.errors import PhysicsError, ValidationError
from gemini.modules.declarations import Output
from gemini.types import Ports, Stream
from gemini.types.quantities import Power, PressureDifference, TemperatureDifference
from gemini.types.results import Health, ModuleResult, Values
from gemini.units import Quantity
from tests.fixtures.errors import raises


@pytest.fixture
def values():
    """Return values with declared power and difference quantities."""
    declarations = {
        "power": Output(Power),
        "head": Output(PressureDifference),
        "rise": Output(TemperatureDifference),
        "label": Output(str),
    }
    return Values({"power": 2000.0, "head": 1e5, "rise": 10.0, "label": "x"}, declarations)


def test_values_mapping_and_unit_conversion(values):
    """Values convert on request; differences convert by scale only."""
    assert values.power == values["power"] == 2000.0
    assert values.get("power", unit="kW") == 2
    assert values.get("head", unit="barg") == 1
    assert values.get("rise", unit="degC") == 10
    assert values.get("missing", 5) == 5
    with raises(ValidationError, "invalid_unit", match="label"):
        values.get("label", unit="m")


def test_unknown_values_suggest_close_names(values):
    """Misspelled names list the valid names and the closest one."""
    with raises(
        ValidationError, "unknown_port", match="'powr'.*valid names: power.*did you mean 'power'"
    ):
        values.powr
    with raises(ValidationError, "unknown_port", match="'hed'"):
        values["hed"]


def test_module_result_leaves():
    """Leaves flatten descendant results with relative paths."""
    stream = Stream(m_dot=Quantity(1, "kg/s"), T=Quantity(300, "K"), p=Quantity(1e5, "Pa"))
    leaf = ModuleResult(outputs=Values(), outlets=Ports({"fluid_out": stream}))
    parent = ModuleResult(
        outputs=Values(), outlets=Ports(), children={"a": leaf, "b": leaf}, is_leaf=False
    )
    root = ModuleResult(outputs=Values(), outlets=Ports(), children={"p": parent}, is_leaf=False)
    assert root.leaves() == {"p.a": leaf, "p.b": leaf}
    assert leaf.leaves("x") == {"x": leaf}


def test_health_bounds():
    """The condition score is a fraction."""
    health = Health(score=1, alarm=False, message="ok")
    assert health.assessed and health.score == 1.0 and type(health.score) is float
    assert health.metrics == {}
    with pytest.raises(PhysicsError, match="score"):
        Health(score=1.5, alarm=False, message="bad")
    with pytest.raises(PhysicsError, match="score"):
        Health(score=float("nan"), alarm=False, message="bad")
    with pytest.raises(PhysicsError, match="metrics.drift"):
        Health(score=1, alarm=False, message="bad", metrics={"drift": float("inf")})
    with pytest.raises(TypeError):
        Health(score=1, alarm=False, message="ok", extra=1)


def test_health_holds_arrays_and_checks_every_row():
    """Fields may be arrays over a chunk; the first failing row raises."""
    health = Health(
        score=np.array([1.0, 0.5]),
        alarm=np.array([False, True]),
        message=np.array(["ok", "low"]),
        metrics={"drift": np.array([0.0, 0.2])},
    )
    assert health.message.tolist() == ["ok", "low"] and health.assessed is True
    with pytest.raises(PhysicsError, match="value = 1.5"):
        Health(score=np.array([1.0, 1.5]), alarm=False, message="x")
    with pytest.raises(PhysicsError, match="metrics.drift"):
        Health(score=1, alarm=False, message="x", metrics={"drift": np.array([0.0, np.nan])})


def test_trusted_values_equal_checked_values_and_convert_units():
    """The unchecked constructor of the engine keeps the declarations for unit conversion."""
    declarations = {"power": Output(Power)}
    trusted = Values._trusted({"power": 2000.0}, declarations)
    assert dict(trusted) == dict(Values({"power": 2000.0}, declarations))
    assert trusted.get("power", unit="kW") == 2.0


def chunk_tree():
    """Return a parent over one leaf whose values are arrays over three rows."""
    stream = Stream(
        m_dot=Quantity(np.array([1.0, 2.0, 3.0]), "kg/s"),
        T=Quantity(np.full(3, 300.0), "K"),
        p=Quantity(np.full(3, 1e5), "Pa"),
    )
    leaf = ModuleResult(
        outputs=Values(
            {"power": np.array([1.0, np.nan, 3.0]), "ok": np.array([True, False, True])},
            {"power": Output(float | None), "ok": Output(bool)},
        ),
        outlets=Ports({"fluid_out": stream}),
        inlets=Ports({"fluid_in": stream}),
        inputs={"speed": np.array([5.0, 6.0, 7.0]), "label": "x"},
    )
    root = ModuleResult(
        outputs=Values(),
        outlets=Ports(),
        children={"leaf": leaf},
        call_records=(("leaf", leaf),),
        is_leaf=False,
    )
    return root, leaf


def test_row_gives_plain_python_values_of_one_row():
    """A row of an array tree equals a direct call: float, bool, None, structure kept."""
    root, _ = chunk_tree()
    first, second = root.row(0), root.row(1)
    leaf = first.children["leaf"]
    assert dict(leaf.outputs) == {"power": 1.0, "ok": True}
    assert type(leaf.outputs.power) is float and type(leaf.outputs.ok) is bool
    assert dict(second.children["leaf"].outputs) == {"power": None, "ok": False}
    assert leaf.outlets.fluid_out.m_dot == 1.0 and type(leaf.outlets.fluid_out.T) is float
    assert leaf.inputs == {"speed": 5.0, "label": "x"}
    assert first.call_records[0][1] is leaf and first.leaves() == {"leaf": leaf}
    assert second.children["leaf"].outlets.fluid_out.m_dot == 2.0


def test_mapped_applies_a_function_to_every_value_and_keeps_sharing():
    """Mapping turns every value of the tree; a result in children and records stays one."""
    root, _ = chunk_tree()
    doubled = root.mapped(lambda value: value * 2 if isinstance(value, np.ndarray) else value)
    leaf = doubled.children["leaf"]
    assert leaf.outputs.power[0] == 2.0 and leaf.inputs["speed"].tolist() == [10.0, 12.0, 14.0]
    assert leaf.outlets.fluid_out.m_dot.tolist() == [2.0, 4.0, 6.0]
    assert doubled.call_records[0][1] is leaf and doubled.is_leaf is False
    assert leaf.outlets.fluid_out.fluid is root.children["leaf"].outlets.fluid_out.fluid


def test_health_numbers_that_are_numpy_scalars_become_floats():
    """A NumPy integer (an ``int`` literal inside an ops scope) is a ``float`` score and metric."""
    for zero_or_one in (np.int64(0), np.int64(1), np.float32(1)):
        health = Health(score=zero_or_one, alarm=False, message="ok", metrics={"m": zero_or_one})
        assert type(health.score) is float and type(health.metrics["m"]) is float
