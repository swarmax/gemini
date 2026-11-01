"""``gm.Constraint``: plain data, validated without a plant."""

import pytest

import gemini as gm
from gemini.errors import ValidationError
from tests.fixtures.errors import raises
from tests.fixtures.json_schema import check


@pytest.mark.parametrize(
    "constraint",
    [
        gm.Constraint(
            "d*.reservoir.liquid_flow",
            min={"value": 50, "unit": "m3/h"},
            max={"value": 300, "unit": "m3/h"},
            when="running",
        ),
        gm.Constraint("d*.brine_cooling", max=40),
        gm.Constraint(
            "d*.reservoir.liquid_flow",
            equals={"value": 330, "unit": "d"},
            over="duration",
            when="running",
        ),
        gm.Constraint("grid.power_out", max={"value": 5, "unit": "MW"}, over="mean"),
    ],
)
def test_a_round_trip_gives_the_same_constraint(constraint):
    """``from_dict`` of ``to_dict`` is equal, and the dictionary fits the schema."""
    data = constraint.to_dict()
    assert gm.Constraint.from_dict(data) == constraint
    assert check(data, gm.Constraint.schema()) == []


@pytest.mark.parametrize(
    "arguments,code",
    [
        ({"path": "d0.flow"}, "missing_value"),
        ({"path": "flow", "max": 1}, "invalid_value"),
        ({"path": 3, "max": 1}, "invalid_value"),
        ({"path": "d0.flow", "max": 1, "over": "median"}, "invalid_value"),
        ({"path": "d0.flow", "max": 1, "when": "stopped"}, "invalid_value"),
        ({"path": "d0.flow", "max": [1]}, "invalid_value"),
        ({"path": "d0.flow", "max": {"value": 1, "unit": "parsec"}}, "invalid_unit"),
    ],
)
def test_what_no_plant_could_make_right_is_refused(arguments, code):
    """Each refusal has its code."""
    with raises(ValidationError, code):
        gm.Constraint(**arguments)


def test_from_dict_names_an_unknown_key():
    """A misspelled key suggests the right one, and a dict without a path is refused."""
    with raises(ValidationError, "unknown_name", match="did you mean 'equals'"):
        gm.Constraint.from_dict({"path": "d0.flow", "equal": 1})
    with raises(ValidationError, "missing_value"):
        gm.Constraint.from_dict({"max": 1})
