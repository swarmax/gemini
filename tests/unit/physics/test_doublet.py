"""The design of a doublet: which child values each group of design values gives."""

import pytest

from gemini.physics import doublet

COLUMN = {"depth": 2500.0, "gradient": 0.03, "surface_temperature": 283.15}
FLOW_PATH = {
    "permeability": 1e-13,
    "thickness": 100.0,
    "well_diameter": 0.2,
    "drainage_radius": 1000.0,
}
PUMP = {"nominal_flow": 0.05, "pump_efficiency": 0.7, "nominal_wellhead_pressure": 2e5}
SKINS = {"reservoir": 0.0, "sink": 0.0}


def values(*groups):
    """Return the design values of ``groups``, every other one unset."""
    empty = dict.fromkeys(doublet.COLUMN + doublet.FLOW_PATH + doublet.PUMP)
    return empty | {"drainage_radius": 1000.0} | {k: v for item in groups for k, v in item.items()}


def design(*groups, pressure=None):
    """Return the child values of a doublet of 1000 kg/m3 and 1 mPa.s."""
    return doublet.design(values(*groups), 1000.0, 1e-3, SKINS, pressure)


def test_an_incomplete_group_derives_nothing():
    """Without the whole column there is nothing to derive."""
    assert design({"depth": 2500.0}) == {}


def test_each_group_adds_its_values():
    """The column gives temperatures, the flow paths the wells, the pump the curves."""
    column = design(COLUMN)
    assert column["reservoir.temperature"] == pytest.approx(283.15 + 0.03 * 2500)
    assert "well.section_length" not in column
    flow = design(COLUMN, FLOW_PATH)
    assert column.keys() < flow.keys() and "well.section_length" in flow
    assert "esp.head_coefficients" not in flow
    assert "esp.head_coefficients" in design(COLUMN, FLOW_PATH, PUMP)


def test_a_stated_pressure_sizes_the_pump():
    """A reservoir pressure stated by hand changes the pump, not the derived pressure."""
    plain = design(COLUMN, FLOW_PATH, PUMP)
    stated = design(COLUMN, FLOW_PATH, PUMP, pressure=2.6e7)
    assert plain["reservoir.pressure"] == stated["reservoir.pressure"]
    assert plain["esp.setting_depth"] != stated["esp.setting_depth"]
