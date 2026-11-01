"""The plant file sections that every module tree shares."""

import json

import pytest

import gemini as gm
from gemini._utils.files import from_json
from gemini.errors import ValidationError
from gemini.modules._utils import serialization
from tests.fixtures import FIXTURES
from tests.fixtures.errors import raises


def test_a_tree_that_is_no_plant_stores_flat_params():
    """What a checkpoint keeps of a root that is no plant reads back to itself."""
    exchanger = gm.modules.HeatExchanger().set_params(
        "", {"hot_nominal_pressure_drop": {"value": 2, "unit": "bar"}}
    )
    data = serialization.tree_dict(exchanger)
    assert data["format"] == 2 and data["params"]["hot_nominal_pressure_drop"] == 2e5
    assert json.dumps(data, allow_nan=False)
    rebuilt = serialization.tree_from_dict(gm.modules.HeatExchanger, data)
    assert serialization.tree_dict(rebuilt) == data


def test_fluids_bindings_and_history_round_trip():
    """Non-default sections are written and read back."""
    exchanger = gm.modules.HeatExchanger().set_params("", {"thermal_conductance": 1.0})
    exchanger.fluid = gm.WATER
    exchanger.set_bindings("", {"duty": {"column": "d", "unit": "kW"}})
    exchanger.set_params("", {"thermal_conductance": 2.0}, valid_from="2020-01-01")
    spec = serialization.tree_dict(exchanger)
    assert spec["fluids"][""]["kind"] == "water" and "boundary" not in spec
    loaded = serialization.tree_from_dict(gm.modules.HeatExchanger, spec)
    assert loaded.fluid == gm.WATER and serialization.tree_dict(loaded) == spec


def test_old_files_are_refused():
    """Format 1 raises ``old_format``."""
    with raises(ValidationError, "old_format") as caught:
        gm.Plant.from_dict({"version": 1, "modules": {}})
    assert caught.value.code == "old_format"
    with raises(ValidationError, "old_format"):
        gm.Plant.from_dict(from_json(FIXTURES / "plant_format1.json"))
    assert serialization.format_error({"format": 3}).code == "invalid_format"


def test_a_strict_report_raises_and_a_collecting_one_keeps_going():
    """``guard`` turns errors into problems with the path of the spec."""
    report = serialization.Report()
    with report.guard("a.b"):
        raise ValidationError("bad", path="c", suggestions=["x"])
    assert report.items == [
        {"path": "a.b.c", "message": "bad", "code": "invalid_value", "suggestions": ["x"]}
    ]
    with pytest.raises(ValidationError), serialization.Report(strict=True).guard("a"):
        raise ValidationError("bad")


def test_skips_matches_a_broken_module_and_its_children():
    """A module that failed to build hides the problems that only follow from it."""
    report = serialization.Report()
    report.broken.add("a")
    assert report.skips("a") and report.skips("a.b") and not report.skips("ab")


def test_keep_stated_keeps_equal_values_only():
    """A stated value stays while it still parses to the current one."""
    assert serialization.keep_stated("5", 5, int) == "5"
    assert serialization.keep_stated("5", 6, int) is None
    assert serialization.keep_stated("x", 6, int) is None
