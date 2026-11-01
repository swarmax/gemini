"""The field a constraint reads and its columns."""

import gemini as gm
from gemini.evaluate._utils import columns
from tests.fixtures.costed_plants import heating_plant
from tests.fixtures.errors import raises
from tests.fixtures.result_tables import make_results


def test_a_port_quantity_is_part_of_the_field():
    """A port quantity belongs to the field, not to the module path."""
    assert columns.split_target("heat.return_out.temperature") == (
        "heat",
        "return_out.temperature",
    )
    assert columns.split_target("d*.brine_cooling") == ("d*", "brine_cooling")


def test_field_of_returns_the_module_and_the_field():
    """The module must be in the plant and the field must exist on it."""
    assert columns.field_of(heating_plant(), "heat.unmet_demand") == ("heat", "unmet_demand")
    assert columns.field_of(heating_plant(), "heat.supply_in.temperature") == (
        "heat",
        "supply_in.temperature",
    )


def test_field_of_refuses_an_unknown_module_and_an_unknown_field():
    """Both raise ``unknown_name``."""
    with raises(gm.errors.ValidationError, "unknown_name", match="not in the plant"):
        columns.field_of(heating_plant(), "cool.unmet_demand")
    with raises(gm.errors.ValidationError, "unknown_name", match="no field"):
        columns.field_of(heating_plant(), "heat.unmet")


def test_a_parameter_is_told_from_an_output():
    """``return_temperature`` is a parameter of the heat consumer, ``unmet_demand`` an output."""
    plant = heating_plant()
    assert columns.is_parameter(plant, "heat", "return_temperature") is True
    assert columns.is_parameter(plant, "heat", "unmet_demand") is False


def test_a_parameter_takes_the_value_it_has_in_the_run():
    """The latest value of an undated module, as a one-element array."""
    plant = heating_plant()
    plant.set_params("heat", {"return_temperature": 303.15})
    frame = make_results({"heat": {"unmet_demand": [1.0]}}).to_frame()
    assert list(columns.parameter_values(plant, frame, "heat", "return_temperature")) == [303.15]


def test_a_column_the_run_lacks_gives_nothing():
    """No column, no values and no steps."""
    frame = make_results({"heat": {"unmet_demand": [1.0], "operating": [1.0]}}).to_frame()
    values, active = columns.series(heating_plant(), frame, "heat", "surplus")
    assert values.size == 0 and active.size == 0
    values, active = columns.series(heating_plant(), frame, "heat", "unmet_demand")
    assert list(values) == [1.0] and list(active) == [True]
