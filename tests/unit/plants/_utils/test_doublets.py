"""The plants on a chosen number of doublets: size, wiring and depth."""

import pytest

import gemini as gm
from gemini.errors import ValidationError
from tests.fixtures.designs import design_values
from tests.fixtures.errors import raises
from tests.fixtures.esp_design import ESP_DESIGN
from tests.fixtures.heating_cooling import days_case

BRINE = gm.Fluid(
    density=1030,
    viscosity={"value": 0.4, "unit": "mPa*s"},
    gas_liquid_ratio=0.8,
    gas_composition={"CH4": 0.8, "CO2": 0.2},
)
TEMPLATES = (
    "HeatingPlant",
    "HeatingCoolingPlant",
    "HeatingFullCoolingPlant",
    "HeatingAbsorptionCoolingPlant",
    "HeatingHeatPumpCoolingPlant",
)
WELL_DESIGN = {
    "well_diameter": {"value": 0.244, "unit": "m"},
    "nominal_flow": {"value": 300, "unit": "m3/h"},
    "pump_efficiency": 0.7,
    "nominal_wellhead_pressure": {"value": 10, "unit": "bar"},
} | ESP_DESIGN
SIZES = {
    "degasser.separation_efficiency": 1.0,
    "injection_pump.efficiency": 0.7,
    "injection_pump.pump_type": "unspecified",
    "heat_exchanger.thermal_conductance": {"value": 1500000, "unit": "W/K"},
    "heat_exchanger.hot_nominal_pressure_drop": {"value": 0, "unit": "bar"},
    "heat_exchanger.cold_nominal_pressure_drop": {"value": 0, "unit": "bar"},
    "heat_exchanger.hot_nominal_mass_flow": {"value": 100, "unit": "kg/s"},
    "heat_exchanger.cold_nominal_mass_flow": {"value": 100, "unit": "kg/s"},
    "peak_boiler.capacity": {"value": 30, "unit": "MW"},
    "peak_boiler.efficiency": 0.9,
    "heating_consumer.return_pressure": {"value": 6, "unit": "bar"},
}
PIPE = {
    "length": {"value": 100, "unit": "m"},
    "inner_diameter": {"value": 0.3, "unit": "m"},
    "elevation_change": {"value": 0, "unit": "m"},
    "heat_transfer_coefficient": 1,
}
INPUTS = {
    "peak_boiler.temperature_setpoint": {"value": 100, "unit": "degC"},
    "injection_pump.pressure_setpoint": {"value": 60, "unit": "bar"},
}
GEOTHERM = {
    f"d{index}.{name}": value
    for index in range(2)
    for name, value in (
        ("gradient", {"value": 30, "unit": "K/km"}),
        ("surface_temperature", {"value": 12, "unit": "degC"}),
    )
}


def designed(count):
    """Return a heating plant on ``count`` doublets with the sample problem's values."""
    plant = gm.plants.HeatingPlant(doublets=count)
    values = {"depth": {"value": 2500, "unit": "m"}} | SIZES
    for index in range(count):
        values |= {f"d{index}.{name}": value for name, value in WELL_DESIGN.items()}
    for pipe in ("heating_return_pipe", "heating_supply_pipe"):
        values |= {f"{pipe}.{name}": value for name, value in PIPE.items()}
    plant.set_params("", design_values(plant) | values)
    return plant.set_inputs(INPUTS)


@pytest.mark.parametrize("name", TEMPLATES)
@pytest.mark.parametrize("count", [1, 2, 3])
def test_every_template_takes_one_to_three_doublets(name, count):
    """The doublets are ``d0`` to ``d{n-1}``, the structure has no open port, the size is stored."""
    plant = getattr(gm.plants, name)(doublets=count)
    assert [hasattr(plant, f"d{index}") for index in range(4)] == [
        index < count for index in range(4)
    ]
    assert gm.plants.validate(plant, on_error="record") == []
    assert plant.to_dict()["size"] == {"doublets": count}


@pytest.mark.parametrize("count", [0, 4])
def test_a_size_outside_the_range_of_the_class_is_refused(count):
    """A plant dict with an impossible size reaches the same error."""
    with raises(ValidationError, "invalid_design", match="doublets"):
        gm.plants.HeatingPlant(doublets=count)


@pytest.fixture(scope="module", params=[1, 2, 3])
def stored(request):
    """Return ``(count, plant dict, plant read from it)``."""
    data = designed(request.param).to_dict()
    return request.param, data, gm.Plant.from_dict(data)


def test_a_plant_round_trips(stored):
    """The plant read from the dict of each size writes the same dict."""
    count, data, built = stored
    assert data["size"] == {"doublets": count}
    assert built.to_dict() == data


def test_a_plant_runs_one_day(stored):
    """A stored plant of each size plans a day and delivers it."""
    count, _, built = stored
    case = days_case([8e6 * count], start="2027-01-28")
    clock = gm.engine.Clock.days(2027, 1, 28, step="24h")
    results = gm.simulate(built, case, clock=clock)
    delivered = gm.evaluate.totals(built, case, results)["heat_delivered"].value
    assert delivered == pytest.approx(8e6 * count * 86400, rel=2e-3)


def test_depth_gives_the_reservoir_of_every_doublet():
    """3000 m at 30 K/km from 12 degC is 102 degC, and the pressure the brine column's."""
    plant = gm.plants.HeatingPlant(doublets=2)
    plant.d0.fluid = plant.d1.fluid = BRINE
    plant.set_params("", {"depth": {"value": 3000, "unit": "m"}} | GEOTHERM)
    for doublet in (plant.d0, plant.d1):
        assert doublet.reservoir.temperature == pytest.approx(375.15)
        assert doublet.sink.temperature == pytest.approx(375.15)
        assert doublet.reservoir.pressure == pytest.approx(1030 * 9.81 * 3000 + 101325)


def test_an_explicit_temperature_wins_and_stays_stated():
    """A child value of one doublet is kept against a later depth, on that doublet alone."""
    plant = gm.plants.HeatingPlant(doublets=2)
    plant.set_params(
        "",
        {
            "depth": {"value": 3000, "unit": "m"},
            "d1.reservoir.temperature": {"value": 90, "unit": "degC"},
        }
        | GEOTHERM,
    )
    plant.set_params("", {"depth": {"value": 2000, "unit": "m"}})
    assert plant.d0.reservoir.temperature == pytest.approx(345.15)
    assert plant.d1.reservoir.temperature == pytest.approx(363.15)
    assert gm.Plant.from_dict(plant.to_dict()).d1.reservoir.temperature == pytest.approx(363.15)


def test_the_stored_plant_keeps_the_depth_and_no_derived_value():
    """Only what was given is stored: the depth, not that of each doublet, nor the geotherm."""
    plant = gm.plants.HeatingPlant(doublets=2)
    plant.set_params("", {"depth": {"value": 3000, "unit": "m"}} | GEOTHERM)
    assert plant.to_dict()["params"] == {"depth": {"value": 3000, "unit": "m"}}


def test_a_depth_on_a_plant_waits_for_the_geotherm_of_each_doublet():
    """The geotherm may come later, as a site value does."""
    plant = gm.plants.HeatingPlant(doublets=1).set_params(
        "", {"depth": {"value": 3000, "unit": "m"}}
    )
    assert plant.d0.depth == 3000.0
    assert plant.d0.reservoir._params_at(None).get("temperature") is None


def test_the_geotherm_of_one_doublet_may_come_in_the_call_of_the_depth():
    """``depth`` goes to each doublet in the same call that gives the doublet its geotherm."""
    plant = gm.plants.HeatingPlant(doublets=1)
    geotherm = {
        "d0.surface_temperature": {"value": 12, "unit": "degC"},
        "d0.gradient": {"value": 30, "unit": "K/km"},
    }
    plant.set_params("", {"depth": {"value": 3000, "unit": "m"}} | geotherm)
    assert plant.d0.reservoir.temperature == pytest.approx(375.15)
