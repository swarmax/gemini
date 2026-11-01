"""Calling a module row by row: streams and inputs per row, exact errors, restored inputs."""

import numpy as np
import pytest

import gemini as gm
from gemini.engine.rows import (
    applied,
    inlet_feeds,
    row_item,
    row_streams,
    run_rows,
    stack_column,
    stacked,
)
from tests.fixtures.engine_plants import Booster, Reservoir


def _streams(rows):
    return {
        "fluid_in": gm.Stream(
            m_dot=gm.units.Quantity(np.arange(1.0, rows + 1), "kg/s"),
            T=gm.units.Quantity(np.full(rows, 300.0), "K"),
            p=gm.units.Quantity(np.full(rows, 1e5), "Pa"),
            fluid=gm.WATER,
        )
    }


def test_row_helpers_read_one_row_and_stack_the_rows_back():
    """A scalar holds for every row, ``None`` is NaN and a stream is built from its fields."""
    assert row_item(np.array([1.0, 2.0]), 1) == 2.0 and row_item(5.0, 3) == 5.0
    assert np.isnan(stack_column([1.0, None])).tolist() == [False, True]
    streams = row_streams({"fluid_in": gm.WATER}, lambda port, field: 1.0)
    assert streams["fluid_in"].m_dot == 1.0
    assert sorted(inlet_feeds(_streams(2))) == ["fluid_in.T", "fluid_in.m_dot", "fluid_in.p"]


def test_each_row_is_a_call_with_its_own_error():
    """A failing row is an error and NaN in the stack; the others are real results."""
    module = Booster()
    streams = _streams(3)
    feeds = inlet_feeds(streams) | {"level": np.array([1.0, -1.0, 3.0])}
    results, errors, states = run_rows(module, {"fluid_in": gm.WATER}, feeds, 3, {}, False)
    assert sorted(results) == [0, 2] and list(errors) == [1] and states is None
    assert "level = -1.0" in str(errors[1])
    assert stacked(results, 3).outputs["rise"].tolist()[::2] == [2.0, 6.0]
    assert np.isnan(stacked(results, 3).outputs["rise"][1])
    assert stacked({}, 3) is None


def test_a_stepped_module_carries_its_state_from_row_to_row():
    """The states after the last row are those of the sum of the flows."""
    streams = _streams(3)
    feeds = inlet_feeds(streams)
    _, errors, states = run_rows(Reservoir(), {"fluid_in": gm.WATER}, feeds, 3, {"dt": 900.0}, True)
    assert errors == {} and states == {"total": 6.0}


def test_applied_inputs_are_validated_and_put_back():
    """A bad value raises and an input is only held for the block."""
    module = Booster()
    module._set_inputs({"level": 0.5})
    with applied(module, {"level": 2.0}):
        assert module._input_values["level"] == 2.0
    assert module._input_values["level"] == 0.5
    with pytest.raises(gm.errors.ValidationError):
        with applied(module, {"level": "x"}):
            pass
    with applied(module, {"level": np.array([1.0, 2.0])}):
        assert module._input_values["level"].tolist() == [1.0, 2.0]
    with pytest.raises(gm.errors.ValidationError):
        with applied(module, {"level": np.array([1.0, "x"], dtype=object)}):
            pass
    assert module._input_values["level"] == 0.5
