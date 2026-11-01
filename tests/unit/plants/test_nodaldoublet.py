"""``NodalDoublet``: rate and pump head from nodal analysis, on the values of its examples."""

import pytest

import gemini as gm
from gemini.physics.geometry import build_path, section_values
from tests.fixtures.sample_cases import example_plant

PRODUCER_SURVEY = [
    (0, 0, 0.1778),
    (400, 400, 0.1778),
    (550, 550, 0.1778),
    (700, 700, 0.1778),
    (904, 900, 0.273),
    (1062, 1050, 0.273),
    (1243, 1200, 0.273),
    (1348, 1300, 0.273),
    (1634, 1500, 0.273),
    (2152, 1900, 0.273),
]
INJECTOR_SURVEY = [
    (0, 0, 0.1616964),
    (148, 148, 0.1616964),
    (1097, 1034, 0.25273),
    (2109, 1742, 0.1616964),
    (2327, 1883, 0.0995668),
]
RESERVOIR = dict(
    temperature={"value": 80, "unit": "degC"},
    permeability=1e-12,
    aquifer_thickness=100,
    drainage_radius=0,
    wellbore_radius=0.1,
)
RETURNED = gm.Stream(
    flow={"value": 125.1, "unit": "m3/h"},
    T={"value": 40, "unit": "degC"},
    p={"value": 3, "unit": "bar"},
)


def path_of(stations):
    """Return the section lists of the well path of survey stations with 2e-5 m roughness."""
    path = build_path([dict(MD=md, TVD=tvd, ID=bore, roughness=2e-5) for md, tvd, bore in stations])
    return section_values(path)


HEAD_COEFFICIENTS = [
    125.518426,
    -0.0020852856,
    2.28955651e-07,
    -1.45640214e-11,
    2.37859645e-16,
    -1.18258356e-21,
]


@pytest.fixture
def deviated():
    """Return the doublet of the parallel exchangers case: 18 stages, 2.3 m3/h/bar injector."""
    doublet = example_plant("NodalDoublet")
    doublet.reservoir.set_params(
        "",
        {
            "pressure": {"value": 216, "unit": "bar"},
            "productivity_index": 1.76 / 3.6e8,
            "top_depth": 1900,
            **RESERVOIR,
        },
    )
    producer = dict(
        **path_of(PRODUCER_SURVEY),
        soil_temperature={"value": 20, "unit": "degC"},
        esp_depth=550,
    )
    doublet.well.set_params("", {"segment": "below_esp", **producer})
    doublet.riser.set_params("", {"segment": "above_esp", **producer})
    doublet.esp.set_params(
        "",
        {
            "stage_count": 18,
            "head_coefficients": HEAD_COEFFICIENTS,
        },
    )
    doublet.injector.set_params("", path_of(INJECTOR_SURVEY))
    doublet.sink.set_params(
        "",
        {
            "pressure": {"value": 180, "unit": "bar"},
            "injectivity_index": 2.3 / 3.6e8,
            "top_depth": 1883,
            **RESERVOIR,
        },
    )
    doublet.esp.frequency = {"value": 60, "unit": "Hz"}
    doublet.wellhead_pressure = {"value": 10, "unit": "bar"}
    return doublet


@pytest.fixture
def vertical():
    """Return the example doublet of the boiler and CHP case at 65 Hz and 3 bar."""
    doublet = example_plant("NodalDoublet")
    doublet.esp.frequency = {"value": 65, "unit": "Hz"}
    doublet.wellhead_pressure = {"value": 3, "unit": "bar"}
    return doublet


def test_it_is_a_registered_plant():
    """The class is in the registry as a plant, and in ``gm.modules`` with the other plants."""
    assert "NodalDoublet" in gm.plants.names()
    assert gm.modules.get("NodalDoublet") is gm.plants.NodalDoublet
    assert isinstance(gm.plants.get("NodalDoublet"), gm.plants.NodalDoublet)
    assert gm.plants.NodalDoublet.category == "plants"


def test_produce_finds_the_rate_of_the_wellhead_pressure(deviated, vertical):
    """Both example wells deliver their wellhead pressure at the rate of the upstream cases."""
    for doublet, rate, pressure in ((deviated, 125.10, 10e5), (vertical, 129.02, 3e5)):
        supply = doublet(return_in=RETURNED).outlets.supply_out
        assert round(supply.m_dot * 3.6, 2) == rate
        assert supply.p == pytest.approx(pressure, rel=1e-6)


def test_inject_commands_the_pump_to_the_solved_pressure(deviated):
    """With the upstream injectivity the injector needs 54.86 bar, from a 3 bar suction."""
    pump = deviated(return_in=RETURNED).children["injection_pump"]
    assert round(pump.outputs.get("discharge_pressure", unit="bar"), 2) == 54.86
    assert round(pump.inlets.power_in / 1e3, 1) == 225.3


def test_inject_adds_nothing_when_no_pump_is_needed(vertical):
    """The 3100 m column over-delivers, so the pump stays at its suction and draws nothing."""
    pump = vertical(return_in=RETURNED).children["injection_pump"]
    assert pump.inlets.power_in == 0
    assert pump.outlets.fluid_out.p == RETURNED.p


def test_a_call_closes_mass_and_hands_power_and_losses_on(vertical):
    """The call draws the power of the ESP and the pump; the formation takes every loss."""
    result = vertical(return_in=RETURNED)
    assert result.inlets.power_in == result.children["esp"].inlets.power_in
    assert len(result.children["formation"].inlets.heat_in) == 3
    assert gm.modules.mass_balance(vertical, result)["residual"] == 0
