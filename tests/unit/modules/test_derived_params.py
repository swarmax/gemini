"""A composite derives its children's values on every route that sets parameters."""

import pytest

import gemini as gm
from gemini._utils import registry
from gemini.physics import hydraulics
from tests.fixtures.deriving import Column

HEIGHT, DENSITY = 2500.0, 1030.0
PRESSURE = hydraulics.hydrostatic_dp(DENSITY, HEIGHT)
GIVEN = {"height": {"value": 2500, "unit": "m"}, "density": {"value": 1030, "unit": "kg/m3"}}


@pytest.fixture(autouse=True)
def registered(monkeypatch):
    """Register the test composite for the spec routes, in a copy of the registry."""
    monkeypatch.setattr(registry, "_entries", dict(registry._entries))
    registry.register(Column)


def plant_with(params):
    """Return a plant that holds one column with ``params``."""
    plant = gm.Plant("Holder")
    plant.add("Column", name="column", params=params)
    return plant


def test_a_direct_call_derives():
    """``set_params`` on the composite derives the child value."""
    column = Column()
    column.set_params("", GIVEN)
    assert column.reservoir.pressure == PRESSURE


def test_values_may_arrive_one_call_at_a_time():
    """A value still missing derives nothing; the last one completes the derivation."""
    column = Column()
    column.set_params("", {"height": HEIGHT})
    assert not column.reservoir.get("pressure").initialized
    column.set_params("", {"density": DENSITY})
    assert column.reservoir.pressure == PRESSURE


@pytest.mark.parametrize(
    "assign",
    [
        lambda column: column.set_params("", {"height": HEIGHT * 2}),
        lambda column: setattr(column, "height", HEIGHT * 2),
    ],
    ids=["update_params", "attribute"],
)
def test_update_params_and_assignment_reach_the_override(assign):
    """An own parameter set by name derives as ``set_params`` does."""
    column = Column()
    column.set_params("", GIVEN)
    assign(column)
    assert column.reservoir.pressure == pytest.approx(PRESSURE * 2)


def test_add_with_params_derives():
    """``Plant.add`` goes through the override."""
    assert plant_with(GIVEN).column.reservoir.pressure == PRESSURE


def test_a_path_and_a_dotted_name_reach_the_override():
    """A parent call at any depth reaches the composite."""
    plant = plant_with({})
    plant.set_params("column", {"density": DENSITY})
    plant.set_params("", {"column.height": HEIGHT})
    assert plant.column.reservoir.pressure == PRESSURE


def test_from_dict_derives_and_keeps_only_what_was_stated():
    """The file holds own and explicit child values; reading it derives the rest."""
    plant = plant_with(GIVEN)
    spec = plant.to_dict()
    assert spec["modules"]["column"]["params"] == GIVEN
    assert gm.Plant.from_dict(spec).column.reservoir.pressure == PRESSURE


def test_an_explicit_child_value_in_the_same_call_wins():
    """The stated child value stays, and stays through later calls and in the file."""
    plant = plant_with(GIVEN | {"reservoir.pressure": {"value": 100, "unit": "bar"}})
    assert plant.column.reservoir.pressure == 1e7
    plant.set_params("column", {"height": 1000.0})
    assert plant.column.reservoir.pressure == 1e7
    spec = plant.to_dict()
    assert spec["modules"]["column"]["params"]["reservoir.pressure"] == {
        "value": 100,
        "unit": "bar",
    }
    assert gm.Plant.from_dict(spec).column.reservoir.pressure == 1e7


def test_an_explicit_child_value_through_a_path_wins():
    """A child value set through the plant is explicit too."""
    plant = plant_with(GIVEN)
    plant.set_params("column.reservoir", {"pressure": 2e7})
    plant.set_params("column", {"height": 1000.0})
    assert plant.column.reservoir.pressure == 2e7
    assert gm.Plant.from_dict(plant.to_dict()).column.reservoir.pressure == 2e7


def test_a_child_override_survives_a_later_derivation():
    """``update_params`` on a child is an explicit override."""
    column = Column()
    column.set_params("", GIVEN)
    column.set_params("", {"reservoir.pressure": 3e7})
    column.set_params("", {"height": 1000.0})
    assert column.reservoir.pressure == 3e7


def test_a_dated_call_derives_at_its_date():
    """A dated design gives a dated child value; the current value does not change."""
    plant = plant_with(GIVEN)
    plant.set_params("column", {"height": 1000.0}, valid_from="2030-01-01")
    assert plant.column.reservoir.pressure == PRESSURE
    later = plant.params_at("column.reservoir", "2031-01-01")["pressure"]
    assert later == hydraulics.hydrostatic_dp(DENSITY, 1000.0)
    assert plant.params_at("column.reservoir", "2029-01-01")["pressure"] == PRESSURE


def test_param_history_is_derived_and_written_without_the_derived_values():
    """A file with a dated design rebuilds the dated child values and stores only the design."""
    plant = plant_with(GIVEN)
    plant.set_params("column", {"height": 1000.0}, valid_from="2030-01-01")
    spec = plant.to_dict()
    assert "column.reservoir" not in spec["param_history"]
    rebuilt = gm.Plant.from_dict(spec)
    assert rebuilt.params_at("column.reservoir", "2031-01-01")["pressure"] == pytest.approx(
        hydraulics.hydrostatic_dp(DENSITY, 1000.0)
    )
    assert rebuilt.params_at("column.reservoir", "2029-01-01")["pressure"] == PRESSURE


def test_a_handwritten_root_stores_no_derived_value():
    """``Module.to_dict`` of the composite itself leaves the derived child value out."""
    column = Column()
    column.set_params("", GIVEN)
    spec = column.to_dict()
    assert "reservoir.pressure" not in spec["params"]
    assert gm.Plant.from_dict(spec).reservoir.pressure == PRESSURE
