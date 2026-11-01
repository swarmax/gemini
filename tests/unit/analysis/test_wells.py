"""Nodal analysis and the pump curve, against the plant's own calls and hand formulas."""

import copy
import json

import pytest

import gemini as gm
from gemini import units
from gemini.analysis import wells
from gemini.physics.geometry import vertical_path
from gemini.types.flows import Stream
from tests.fixtures.errors import raises
from tests.fixtures.sample_cases import example_plant

BAR = 1e5
CASE = {"wellhead_pressure": {"value": 4.6, "unit": "bar"}, "rates": [20, 45], "frequency": 55.484}


@pytest.fixture(scope="module")
def doublet_curves(shared_plant):
    """Return the nodal analysis of the example doublet at two ESP frequencies."""
    faster = dict(CASE, frequency=58.0)
    return wells.nodal(shared_plant, "doublet", [CASE, faster])


def test_the_operating_point_reproduces_the_wellhead_pressure_in_the_plant_call(
    shared_plant, doublet_curves
):
    """Commanding the solved rate and frequency, the doublet delivers the 4.6 bar asked for."""
    point = doublet_curves["cases"][0]["operating_point"]
    doublet = copy.deepcopy(shared_plant).get_submodule("doublet")
    doublet.get_submodule("esp").frequency = CASE["frequency"]
    doublet.get_submodule("reservoir").production_rate = point["rate"]["value"]
    fluid = doublet.get_submodule("reservoir").fluid
    supply = doublet(
        return_in=Stream(m_dot=point["rate"]["value"], T=300.0, p=1e6, fluid=fluid)
    ).outlets
    assert supply.supply_out.p == pytest.approx(4.6 * BAR, rel=1e-9)
    assert point["wellhead_pressure"]["value"] == pytest.approx(4.6 * BAR)


def test_the_lift_curve_falls_with_rate_and_the_inflow_curve_too(doublet_curves):
    """Both curves fall with rate, as the well friction and the drawdown grow."""
    case = doublet_curves["cases"][0]
    for curve in (case["ipr"], case["vlp"]):
        assert len(curve["rate"]["value"]) == wells.CURVE_POINTS
        assert curve["pressure"]["value"] == sorted(curve["pressure"]["value"], reverse=True)


def test_the_inflow_curve_follows_the_linear_productivity_index(shared_plant, doublet_curves):
    """At the first rate, the sandface pressure is reservoir pressure minus flow over index."""
    reservoir = shared_plant.get_submodule("doublet.reservoir")
    rate = doublet_curves["cases"][0]["ipr"]["rate"]["value"][0]
    density = reservoir.fluid.properties(reservoir.pressure, reservoir.temperature).rho_l
    expected = reservoir.pressure - rate / density / reservoir.productivity_index
    assert doublet_curves["cases"][0]["ipr"]["pressure"]["value"][0] == pytest.approx(
        expected, rel=1e-12
    )


def test_a_higher_frequency_lifts_more(doublet_curves):
    """A what-if at a higher pump frequency gives a higher operating rate."""
    slow, fast = (case["operating_point"]["rate"]["value"] for case in doublet_curves["cases"])
    assert fast > slow


def test_the_plant_is_not_changed(shared_plant, doublet_curves):
    """The ESP frequency of a case is set on a copy: the plant's control stays unset."""
    with raises(gm.errors.ValidationError, "missing_value"):
        shared_plant.get_submodule("doublet.esp").frequency


def test_a_bracket_outside_the_well_model_fails_that_case_only():
    """Rates up to 200 kg/s drive the pressure below zero: the case carries the error."""
    plant = example_plant("DoubletHeatPlant")
    cases = [dict(CASE, rates=[20, 200]), CASE]
    with raises(gm.errors.PhysicsError, "out_of_range"):
        wells.nodal(plant, "doublet", cases)
    broken, fine = wells.nodal(plant, "doublet", cases, on_error="record")["cases"]
    assert broken["error"]["code"] == "out_of_range"
    assert broken["ipr"] is None and broken["operating_point"] is None
    assert fine["operating_point"] is not None


def test_inputs_are_checked(shared_plant):
    """A missing pressure, an unknown path and a path without a reservoir are named."""
    with pytest.raises(gm.errors.ValidationError, match="wellhead_pressure") as missing:
        wells.nodal(shared_plant, "doublet", {"rates": [1, 2], "frequency": 50})
    assert missing.value.code == "missing_value"
    with raises(gm.errors.ValidationError, "unknown_name"):
        wells.nodal(shared_plant, "doublt", CASE)
    with pytest.raises(gm.errors.ValidationError, match="ProductionReservoir"):
        wells.nodal(shared_plant, "doublet.esp", CASE)


DEPTH = 2500.0
WIDE = 2.0
"""A well this wide has no friction to speak of: the answer is the column of brine."""
INJECTIVITY = 2e-6
RATE = 50.0
BRINE = gm.Fluid(density=1030.0, viscosity=4e-4)


def injector():
    """Return a vertical injector into an aquifer at 280 bar, the path ``"limb"`` of a plant."""
    plant = gm.Plant("Injector")
    limb = gm.modules.ModuleDict(
        {"well": gm.modules.InjectionWell(), "sink": gm.modules.InjectionReservoir()}
    )
    plant._add_module("limb", limb)
    path = vertical_path(DEPTH, WIDE, 2e-5).model_dump()
    limb["well"].set_params(
        "",
        {
            "pipe_path": path,
            "soil_temperature": {"value": 50, "unit": "degC"},
            "heat_transfer_coefficient": 0.0,
        },
    )
    limb["sink"].set_params(
        "",
        {
            "pressure": {"value": 280, "unit": "bar"},
            "temperature": {"value": 87, "unit": "degC"},
            "permeability": 2e-13,
            "aquifer_thickness": 100.0,
            "drainage_radius": 1000.0,
            "top_depth": 2450.0,
            "injectivity_index": INJECTIVITY,
            "wellbore_radius": 0.1,
        },
    )
    limb["well"].fluid = limb["sink"].fluid = BRINE
    return plant


def needed(rate):
    """Return the wellhead pressure [Pa] at ``rate``: the aquifer's need less the column."""
    required = 280e5 + rate / 1030.0 / INJECTIVITY
    return required - 1030.0 * 9.81 * DEPTH


def test_an_injection_well_gives_the_wellhead_pressure_a_rate_needs():
    """The operating point of a rate is the column of brine below the aquifer's pressure."""
    case = {"rate": RATE, "rates": [10.0, 100.0], "temperature": {"value": 40, "unit": "degC"}}
    found = wells.nodal(injector(), "limb.well", case)
    point = found["cases"][0]["operating_point"]
    assert point["rate"]["value"] == RATE
    assert point["wellhead_pressure"]["value"] == pytest.approx(needed(RATE), rel=1e-3)
    assert point["sandface_pressure"]["value"] == pytest.approx(280e5 + RATE / 1030.0 / INJECTIVITY)


def test_an_injection_well_gives_the_rate_of_a_wellhead_pressure():
    """The other way round: the same balance, solved for the rate."""
    case = {
        "wellhead_pressure": needed(RATE),
        "rates": [10.0, 100.0],
        "temperature": {"value": 40, "unit": "degC"},
    }
    found = wells.nodal(injector(), "limb.sink", case)
    assert found["cases"][0]["operating_point"]["rate"]["value"] == pytest.approx(RATE, rel=1e-3)


def test_injection_curves_have_the_shape_of_production():
    """21 points of the pressure the aquifer needs and the wellhead pressure that gives it."""
    case = {
        "rate": RATE,
        "rates": [{"value": 36, "unit": "t/h"}, 100.0],
        "temperature": {"value": 40, "unit": "degC"},
    }
    found = wells.nodal(injector(), "limb.well", case, units={"pressure": "bar"})["cases"][0]
    assert set(found) == {"conditions", "ipr", "vlp", "operating_point", "error"}
    assert len(found["ipr"]["pressure"]["value"]) == wells.CURVE_POINTS
    assert found["vlp"]["pressure"]["unit"] == "bar"
    assert found["vlp"]["rate"]["value"][0] == pytest.approx(10.0)
    assert found["vlp"]["pressure"]["value"][0] == pytest.approx(needed(10.0) / 1e5, rel=1e-3)
    assert found["ipr"]["pressure"]["value"][-1] == pytest.approx(
        (280e5 + 100.0 / 1030.0 / INJECTIVITY) / 1e5
    )


def test_a_column_that_is_enough_needs_no_wellhead_pressure():
    """Below the lowest pressure a well can hold, no pump is needed: the value says so."""
    plant = injector()
    plant.get_submodule("limb.sink").pressure = {"value": 200, "unit": "bar"}
    case = {"rate": RATE, "rates": [10.0, 100.0], "temperature": {"value": 40, "unit": "degC"}}
    point = wells.nodal(plant, "limb.well", case)["cases"][0]["operating_point"]
    assert point["wellhead_pressure"]["value"] is None
    assert "no pump" in point["wellhead_pressure"]["reason"]


def test_an_injection_case_needs_a_rate_or_a_pressure():
    """One of them says which way to solve."""
    case = {"rates": [10.0, 100.0], "temperature": {"value": 40, "unit": "degC"}}
    with raises(gm.errors.ValidationError, "missing_value", match="wellhead_pressure"):
        wells.nodal(injector(), "limb.well", case)


def test_a_failed_injection_case_is_recorded():
    """As in production, the other cases still run."""
    cases = [
        {"rate": RATE, "rates": [10.0, 100.0]},
        {"rate": RATE, "rates": [10.0, 100.0], "temperature": {"value": 40, "unit": "degC"}},
    ]
    found = wells.nodal(injector(), "limb.well", cases, on_error="record")["cases"]
    assert found[0]["error"]["code"] == "missing_value" and found[1]["error"] is None


def test_the_injection_side_of_a_doublet_is_reached_through_its_injector(shared_plant):
    """The doublet itself is its production chain; the injector names the other side."""
    assert wells._chain(shared_plant, "doublet.injector").well is shared_plant.doublet.injector
    assert wells._chain(shared_plant, "doublet.sink").sink is shared_plant.doublet.sink


def test_pump_curve_starts_at_the_shut_in_head_of_the_polynomial(shared_plant):
    """At zero flow and 60 Hz the head is the first coefficient times the stages, in Pa."""
    pump = shared_plant.get_submodule("doublet.esp")
    curve = wells.pump_curve(shared_plant, "doublet.esp")
    expected = units.ft_head_to_pa(pump.head_coefficients[0] * pump.stage_count)
    assert curve["curve"]["flow"]["value"][0] == 0.0
    assert curve["curve"]["head"]["value"][0] == pytest.approx(expected, rel=1e-12)
    assert curve["frequency"] == {"value": 60.0, "unit": "Hz"}
    assert curve["measured"] == [] and curve["correction"]["value"] is None


def test_pump_curve_recovers_a_known_correction(shared_plant):
    """Points measured at 0.9 times the model head plus 1 kPa give the inverse line back."""
    pump = shared_plant.get_submodule("doublet.esp")
    points = [
        {"flow": flow, "frequency": 55.0, "head": 0.9 * pump.head_function(flow, 55.0) + 1000}
        for flow in (0.02, 0.03, 0.04)
    ]
    curve = wells.pump_curve(shared_plant, "doublet.esp", points)
    assert curve["correction"]["slope"]["value"] == pytest.approx(1 / 0.9, rel=1e-9)
    assert curve["correction"]["offset"]["value"] == pytest.approx(-1000 / 0.9, rel=1e-9)
    assert curve["measured"][0]["theoretical_head"]["value"] == pump.head_function(0.02, 55.0)


def test_pump_curve_with_one_point_has_no_correction_and_says_why(shared_plant):
    """One point cannot fix a line; unit strings are read."""
    point = {
        "flow": {"value": 150, "unit": "m3/h"},
        "frequency": {"value": 55, "unit": "Hz"},
        "head": {"value": 20, "unit": "bar"},
    }
    curve = wells.pump_curve(shared_plant, "doublet.esp", [point])
    assert curve["correction"]["value"] is None
    assert "two or more" in curve["correction"]["reason"]
    assert curve["measured"][0]["flow"]["value"] == pytest.approx(150 / 3600)
    assert curve["measured"][0]["head"]["value"] == 20 * BAR
    json.dumps(curve, allow_nan=False)


def test_pump_curve_needs_an_esp(shared_plant):
    """A path that is not an ESP is refused."""
    with pytest.raises(gm.errors.ValidationError, match="ESP"):
        wells.pump_curve(shared_plant, "doublet.well")


def test_nodal_takes_units_for_its_curves_and_point(shared_plant):
    """Every number of a case is converted; ``units`` has no separate map."""
    plain = wells.nodal(shared_plant, "doublet", CASE)["cases"][0]
    case = wells.nodal(shared_plant, "doublet", CASE, units={"pressure": "bar"})["cases"][0]
    assert case["ipr"]["pressure"]["unit"] == "bar"
    assert case["ipr"]["pressure"]["value"][0] == pytest.approx(
        plain["ipr"]["pressure"]["value"][0] / BAR, rel=1e-12
    )
    assert case["operating_point"]["wellhead_pressure"]["unit"] == "bar"
    assert case["ipr"]["rate"] == plain["ipr"]["rate"]


def test_pump_curve_takes_units(shared_plant):
    """Head is a pressure difference, reached by ``pressure``."""
    curve = wells.pump_curve(shared_plant, "doublet.esp", units={"pressure": "bar"})
    assert curve["curve"]["head"]["unit"] == "bar" and curve["frequency"]["unit"] == "Hz"
    with raises(gm.errors.ValidationError, "invalid_unit"):
        wells.pump_curve(shared_plant, "doublet.esp", units={"pressure": "kW"})
