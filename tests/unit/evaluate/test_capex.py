"""Investment of a plant against the capex of its equipment."""

import pytest

import gemini as gm
from gemini._utils.jsonable import to_plain
from gemini.case._utils.kinds import EQUIPMENT_KINDS
from gemini.evaluate._utils import cost
from gemini.modules import Module
from gemini.modules.pumps import _physics
from gemini.run._utils.apply import apply_case
from gemini.units import Quantity
from tests.fixtures.cases import make_case
from tests.fixtures.costed_plants import heating_plant
from tests.fixtures.errors import raises

ALL = gm.case.Capex(
    drilling=Quantity(1000.0, "currency/m"),
    production_pump=Quantity(0.5, "currency/W"),
    injection_pump=Quantity(0.4, "currency/W"),
    circulation_pump=Quantity(0.2, "currency/W"),
    heat_pump=Quantity(0.67, "currency/W"),
    boiler=Quantity(0.06, "currency/W"),
    electric_boiler=Quantity(0.03, "currency/W"),
    chp=Quantity(0.95, "currency/W"),
    absorption_chiller=Quantity(0.3, "currency/W"),
    adsorption_chiller=Quantity(0.35, "currency/W"),
    compression_chiller=Quantity(0.25, "currency/W"),
    heat_exchanger=Quantity(100.0, "currency/(W/K)"),
    cooler=Quantity(0.1, "currency/W"),
    pipe=Quantity(300.0, "currency/m"),
    thermal_storage=Quantity(50.0, "currency/m3"),
    ice_storage=Quantity(40.0, "currency/m3"),
    degasser=Quantity(1e6, "currency"),
    flare=Quantity(1e5, "currency"),
    gas_makeup=Quantity(2e4, "currency"),
)
"""A factor for every kind."""


def priced(kind, params, capex=ALL):
    """Return the capex of one module in a plant of its own, its ports aside."""
    plant = gm.Plant("One")
    plant.add(kind, name="unit", params=params)
    return gm.evaluate.capex(plant, make_case(finance={"capex": capex}))


@pytest.mark.parametrize(
    "kind, params, expected",
    [
        ("HeatPump", {"mode": "heating", "capacity": {"value": 10, "unit": "MW"}}, 0.67e7),
        ("HeatPump", {"mode": "cooling", "capacity": {"value": 10, "unit": "MW"}}, 0.25e7),
        ("Boiler", {"capacity": {"value": 10, "unit": "MW"}}, 0.06e7),
        ("ElectricBoiler", {"capacity": {"value": 10, "unit": "MW"}}, 0.03e7),
        ("CHP", {"electric_capacity": {"value": 1, "unit": "MW"}}, 0.95e6),
        ("AdsorptionChiller", {"capacity": {"value": 2, "unit": "MW"}}, 0.35 * 2e6),
        ("Cooler", {"capacity": {"value": 3, "unit": "MW"}}, 0.1 * 3e6),
        ("Pipe", {"length": {"value": 120, "unit": "m"}}, 300 * 120),
        ("ThermalStorage", {"volume": {"value": 200, "unit": "m3"}}, 50 * 200),
        ("Degasser", {}, 1.0e6),
        ("Flare", {}, 1e5),
        ("GasMakeup", {}, 2e4),
    ],
    ids=[
        "heat_pump",
        "compression_chiller",
        "boiler",
        "electric_boiler",
        "chp",
        "adsorption_chiller",
        "cooler",
        "pipe",
        "thermal_storage",
        "degasser",
        "flare",
        "gas_makeup",
    ],
)
def test_equipment_costs_come_from_its_design(kind, params, expected):
    """A factor times a capacity, a length or a volume, or a fixed item."""
    assert priced(kind, params).value == pytest.approx(expected)


def test_the_exchanger_and_the_absorption_chiller_cost_by_their_size():
    """Conductance and capacity."""
    exchanger = dict(thermal_conductance={"value": 1e6, "unit": "W/K"})
    assert priced("HeatExchanger", exchanger).value == pytest.approx(1e8)
    chiller = dict(capacity={"value": 1e7, "unit": "W"})
    assert priced("AbsorptionUnit", chiller).value == pytest.approx(3e6)


def test_a_circulation_pump_costs_by_its_shaft_power_at_the_nominal_flow():
    """Hydraulic power over the efficiency, at the flow and the rise of the design."""
    plant = gm.Plant("One")
    pump = plant.add(
        "CirculationPump",
        name="unit",
        params={
            "flow": {"value": 50, "unit": "kg/s"},
            "pressure_rise": {"value": 3, "unit": "bar"},
            "loop_pressure": {"value": 5, "unit": "bar"},
            "efficiency": 0.6,
        },
    )
    density = pump.fluid.properties(0, 0).rho_l
    power = 50 / density * 3e5 / 0.6
    result = gm.evaluate.capex(plant, make_case(finance={"capex": ALL}))
    assert result.value == pytest.approx(0.2 * power)


def test_a_centrifugal_pump_costs_by_its_shaft_power_at_the_best_efficiency_flow():
    """The head of the curve at the best-efficiency flow, over the best efficiency."""
    params = {
        "head_coefficients": [3e5, -1e5, -2e6],
        "rated_frequency": {"value": 50, "unit": "Hz"},
        "best_efficiency": 0.7,
        "best_efficiency_flow": {"value": 0.1, "unit": "m3/s"},
        "motor_efficiency": 0.95,
    }
    head = 3e5 - 1e5 * 0.1 - 2e6 * 0.1**2
    expected = 0.2 * 0.1 * head / 0.7
    assert priced("CentrifugalPump", params).value == pytest.approx(expected)


DESIGN = {
    "depth": {"value": 2500, "unit": "m"},
    "gradient": {"value": 30, "unit": "K/km"},
    "surface_temperature": {"value": 12, "unit": "degC"},
    "permeability": {"value": 200, "unit": "mD"},
    "thickness": {"value": 100, "unit": "m"},
    "well_diameter": {"value": 0.244, "unit": "m"},
}
PUMP = {
    "nominal_flow": {"value": 300, "unit": "m3/h"},
    "pump_efficiency": 0.7,
    "nominal_wellhead_pressure": {"value": 10, "unit": "bar"},
}


def test_a_doublet_pays_for_its_wells_by_the_metre_and_its_pump_by_its_power():
    """The wells together are two depths; the pump is its shaft power at the nominal flow."""
    plant = gm.Plant("One")
    plant.add("Doublet", name="unit", params=DESIGN | PUMP)
    case = make_case(finance={"capex": ALL})
    result = gm.evaluate.capex(plant, case)
    head = apply_case(plant, case).unit.esp.head_coefficients
    power = 300 / 3600 * _physics.head(0.0, 60.0, 1, head) / 0.7
    drilling = sum(
        item.value for item in result.parts["modules"].values() if item.parts["kind"] == "drilling"
    )
    assert drilling == pytest.approx(2 * 2500 * 1000.0)
    assert result.parts["modules"]["unit"].value == pytest.approx(0.5 * power)
    assert result.value == pytest.approx(2 * 2500 * 1000.0 + 0.5 * power)


def test_a_doublet_without_a_nominal_flow_cannot_price_its_pump():
    """Nothing is estimated: the error names the missing design value."""
    plant = gm.Plant("One")
    plant.add("Doublet", name="unit", params=DESIGN)
    with raises(gm.errors.ValidationError, "missing_value", match="nominal_flow"):
        gm.evaluate.capex(plant, make_case(finance={"capex": ALL}))


def test_the_capex_is_the_sum_of_the_modules_with_their_kinds_and_price_year():
    """Per module a value with its kind; the total, the currency and the price year."""
    case = make_case(finance={"capex": ALL, "price_year": 2015, "currency": "EUR"})
    result = gm.evaluate.capex(heating_plant(), case)
    assert to_plain(result) == {
        "value": 1e6,
        "unit": "currency",
        "modules": {"heat": {"value": 1e6, "unit": "currency", "kind": "degasser"}},
        "price_year": {"value": 2015, "unit": "-"},
    }


def test_a_plant_without_equipment_has_no_capex_with_a_reason():
    """The grids are not equipment: nothing is invented."""
    case = make_case(finance={"capex": ALL})
    result = gm.evaluate.capex(heating_plant(costed=False), case, on_error="record")
    assert result.value is None
    assert result.reason == cost.NO_COST
    assert result.unit == "currency"
    with raises(gm.errors.ValidationError, "no_value"):
        gm.evaluate.capex(heating_plant(costed=False), case)


def test_a_factor_the_case_lacks_is_missing_assumption_naming_the_kind():
    """A degasser without a factor: the error names its path, the record says why."""
    case = make_case(finance={"capex": gm.case.Capex(boiler=Quantity(0.06, "currency/W"))})
    recorded = gm.evaluate.capex(heating_plant(), case, on_error="record")
    assert recorded.value is None and "assumptions.finance.capex.degasser" in recorded.reason
    with raises(
        gm.errors.ValidationError,
        "missing_assumption",
        match=r"assumptions\.finance\.capex\.degasser",
    ):
        gm.evaluate.capex(heating_plant(), case)


def test_a_case_without_finance_is_missing_assumption():
    """No finance section, no capex."""
    with raises(gm.errors.ValidationError, "missing_assumption", match="assumptions.finance"):
        gm.evaluate.capex(heating_plant(), make_case())


def test_every_kind_but_the_ice_storage_is_declared_by_a_module():
    """Only the ice storage has no module that declares its kind.

    A heat pump is a ``heat_pump`` or, in cooling mode, a ``compression_chiller``.
    """
    declared = {
        module_class.equipment_kind
        for module_class in _subclasses(Module)
        if isinstance(getattr(module_class, "equipment_kind", None), str)
    }
    declared |= {"heat_pump", "compression_chiller"}
    assert set(EQUIPMENT_KINDS) - declared == {"ice_storage"}


def _subclasses(root):
    """Return every subclass of ``root``, at any depth."""
    found = set()
    for sub in root.__subclasses__():
        found |= {sub} | _subclasses(sub)
    return found
