"""Investment of a plant against the declared costs."""

import pytest

import gemini as gm
from gemini._utils.jsonable import to_plain
from gemini.evaluate._utils import cost
from gemini.modules.pumps import _physics
from tests.fixtures.costed_plants import heating_plant
from tests.fixtures.errors import raises
from tests.fixtures.result_tables import make_problem


def test_capex_is_the_declared_cost_with_its_source():
    """The investment is ``total_cost``'s, in its currency, with year and source."""
    result = gm.evaluate.capex(heating_plant(), make_problem())
    assert to_plain(result) == {
        "value": 1000.0,
        "unit": "currency",
        "price_year": {"value": 2024, "unit": "-"},
        "source": "test fixture",
    }


def test_capex_of_a_plant_without_declared_costs_is_null_with_a_reason():
    """Built-in modules declare no cost: nothing is invented."""
    result = gm.evaluate.capex(heating_plant(costed=False), make_problem(), on_error="record")
    assert result.value is None
    assert result.reason == cost.NO_COST
    assert result.unit == "currency"
    no_euro = gm.evaluate.capex(
        heating_plant(costed=False),
        make_problem(assumptions=gm.Assumptions(currency="USD")),
        on_error="record",
    )
    assert no_euro.unit == "currency"


def test_a_factor_without_a_source_is_asked_for(shared_plant):
    """The heat exchanger has no sourced factor: the error names it, the record says why."""
    recorded = gm.evaluate.capex(shared_plant, make_problem(), on_error="record")
    assert recorded.value is None and "exchanger_cost" in recorded.reason
    with raises(gm.errors.ValidationError, "missing_assumption", match="exchanger_cost"):
        gm.evaluate.capex(shared_plant, make_problem())


COSTS = gm.Assumptions(
    pump_cost=gm.units.Quantity(0.5, "currency/W"),
    exchanger_cost=gm.units.Quantity(100.0, "currency/(W/K)"),
    chiller_cost=gm.units.Quantity(0.3, "currency/W"),
    flare_cost=gm.units.Quantity(1e5, "currency"),
    makeup_cost=gm.units.Quantity(2e4, "currency"),
)


def priced(kind, params):
    """Return the capex of one module in a plant of its own, its ports aside."""
    plant = gm.Plant("One")
    plant.add(kind, name="unit", params=params)
    return gm.evaluate.capex(plant, make_problem(assumptions=COSTS))


@pytest.mark.parametrize(
    "kind, params, expected",
    [
        ("HeatPump", {"mode": "heating", "capacity": {"value": 10, "unit": "MW"}}, 0.67e7),
        ("Boiler", {"capacity": {"value": 10, "unit": "MW"}, "efficiency": 0.9}, 0.06e7),
        (
            "CHP",
            {
                "electric_capacity": {"value": 1, "unit": "MW"},
                "electric_efficiency": 0.4,
                "thermal_efficiency": 0.45,
                "maximum_outlet_temperature": 363.15,
            },
            0.95e6,
        ),
        ("Degasser", {}, 1.0e6),
        ("Flare", {}, 1e5),
        ("GasMakeup", {}, 2e4),
    ],
    ids=["heat_pump", "boiler", "chp", "degasser", "flare", "makeup"],
)
def test_equipment_costs_come_from_its_design(kind, params, expected):
    """A factor times a capacity, or a fixed item."""
    assert priced(kind, params).value == pytest.approx(expected)


def test_the_exchanger_and_the_chiller_cost_by_their_size():
    """Conductance and capacity."""
    exchanger = dict(
        thermal_conductance=1e6,
        hot_nominal_pressure_drop=0,
        cold_nominal_pressure_drop=0,
        hot_nominal_mass_flow=100.0,
        cold_nominal_mass_flow=100.0,
    )
    assert priced("HeatExchanger", exchanger).value == pytest.approx(1e8)
    chiller = dict(
        mode="chiller",
        capacity=1e7,
        characteristic_slope=7e5,
        minimum_driving_difference=10.0,
        rejection_coefficient=2.2,
        evaporator_coefficient=1.2,
        auxiliary_power_ratio=0.01,
    )
    assert priced("AbsorptionUnit", chiller).value == pytest.approx(3e6)


def test_a_doublet_pays_for_its_wells_and_its_pump():
    """Two wells by the metre; the pump by its shaft power at the nominal flow."""
    design = {
        "depth": {"value": 2500, "unit": "m"},
        "gradient": {"value": 30, "unit": "K/km"},
        "surface_temperature": {"value": 12, "unit": "degC"},
        "permeability": {"value": 200, "unit": "mD"},
        "thickness": {"value": 100, "unit": "m"},
        "well_diameter": {"value": 0.244, "unit": "m"},
    }
    wells = 2 * 2500 * 5.7e6 / (2 * 2300)
    assert priced("Doublet", design).value == pytest.approx(wells)
    pump = {
        "nominal_flow": {"value": 300, "unit": "m3/h"},
        "pump_efficiency": 0.7,
        "nominal_wellhead_pressure": {"value": 10, "unit": "bar"},
    }
    plant = gm.Plant("One")
    doublet = plant.add("Doublet", name="unit", params=design | pump)
    power = 300 / 3600 * _physics.head(0.0, 60.0, 1, doublet.esp.head_coefficients) / 0.7
    result = gm.evaluate.capex(plant, make_problem(assumptions=COSTS))
    assert result.value == pytest.approx(wells + 0.5 * power)
    assert "SDE+" in result.parts["source"] and "assumptions.pump_cost" in result.parts["source"]


def test_a_doublet_without_a_design_declares_no_cost():
    """The old way has no depth to price."""
    assert gm.plants.get("Doublet").capex(COSTS) is None


def test_the_site_of_the_problem_gives_the_design_values():
    """A depth the plant does not state comes from the site; the plant itself is unchanged."""
    design = {
        "gradient": {"value": 30, "unit": "K/km"},
        "surface_temperature": {"value": 12, "unit": "degC"},
        "permeability": {"value": 200, "unit": "mD"},
        "thickness": {"value": 100, "unit": "m"},
        "well_diameter": {"value": 0.244, "unit": "m"},
    }
    plant = gm.Plant("One")
    plant.add("Doublet", name="unit", params=design)
    sited = make_problem(site={"unit.depth": {"value": 2500, "unit": "m"}})
    assert gm.evaluate.capex(plant, sited).value == pytest.approx(2 * 2500 * 5.7e6 / 4600)
    assert gm.evaluate.capex(plant, make_problem(), on_error="record").value is None
