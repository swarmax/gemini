"""``gm.schedule``: the controls of a plant from its demand at any step, and a run of them."""

import numpy as np
import pandas as pd
import pytest

import gemini as gm
from gemini.case import (
    CO2,
    Air,
    Assumptions,
    Case,
    Constraint,
    Demand,
    Emissions,
    Environment,
    Finance,
)
from gemini.case import Fluid as CaseFluid
from gemini.case import Ground, Opex, Reservoir, Service, Time
from gemini.physics import constants
from gemini.run.schedule import _doublets_above
from gemini.runtime import settings
from gemini.units import Quantity
from tests.fixtures.designs import with_values
from tests.fixtures.errors import raises
from tests.fixtures.esp_design import ESP_DESIGN
from tests.fixtures.parity import BACKENDS
from tests.fixtures.sample_cases import example_plant, template_dict

DESIGN = {
    "depth": {"value": 2500, "unit": "m"},
    "well_diameter": {"value": 0.244, "unit": "m"},
    "nominal_flow": {"value": 300, "unit": "m3/h"},
    "pump_efficiency": 0.7,
    "nominal_wellhead_pressure": {"value": 10, "unit": "bar"},
} | ESP_DESIGN
PRICES = {"electricity": Quantity(100, "EUR/MWh"), "gas": Quantity(40, "EUR/MWh")}
BRINE = gm.Fluid(density=1030.0, viscosity=4e-4).properties(0, 0)
HEAT_PER_FLOW = BRINE.rho_l * BRINE.cp_l * 40.0
FULL = 300 / 3600 * HEAT_PER_FLOW


def constraint(quantity, on="doublet", **fields):
    """Return a constraint on ``quantity`` of ``on`` with bounds given as ``(value, unit)``."""
    bounds = {
        name: Quantity(*fields.pop(name)) for name in ("min", "max", "equals") if name in fields
    }
    return Constraint(on=on, quantity=quantity, **bounds, **fields)


CONSTRAINTS = [
    constraint("production_flow", min=(50, "m3/h"), max=(300, "m3/h"), when="running"),
    constraint("brine_cooling", max=(40, "K")),
]


def services_of(frame):
    """Return the heating and cooling services of the columns ``frame`` has."""
    services = {
        "heating": Service(
            column="heating_demand",
            unit="W",
            supply_temperature=Quantity(100, "degC"),
            return_temperature=Quantity(60, "degC"),
        ),
        "cooling": Service(
            column="cooling_demand",
            unit="W",
            supply_temperature=Quantity(20, "degC"),
            return_temperature=Quantity(28, "degC"),
        ),
    }
    return {name: item for name, item in services.items() if item.column in frame}


def environment_of(ground=True):
    """Return the site of the sample: ground, reservoir, brine and air."""
    return Environment(
        ground=(
            Ground(surface_temperature=Quantity(12, "degC"), gradient=Quantity(30, "K/km"))
            if ground
            else None
        ),
        reservoir=Reservoir(
            reference_depth=Quantity(2500, "m"),
            thickness=Quantity(100, "m"),
            permeability=Quantity(200, "mD"),
            pressure=Quantity(250, "barg"),
        ),
        fluid=CaseFluid(density=Quantity(1030, "kg/m3"), viscosity=Quantity(0.4, "mPa.s")),
        air=Air(temperature=Quantity(10, "degC")),
    )


def case_of(frame, constraints=(), prices=None, co2=None, ground=True, limits=None):
    """Return a case on ``frame``: the site of the sample, the flow range and cooling, the prices.

    ``constraints`` are added to the flow range and the brine cooling (or to ``limits``);
    ``prices`` replace the electricity and gas prices; ``co2`` is a price per kg of CO2.
    """
    frame = frame.copy()
    frame.attrs = {"units": dict.fromkeys(frame, "W"), "quantities": dict.fromkeys(frame, "power")}
    step = frame.index[1] - frame.index[0] if len(frame) > 1 else pd.Timedelta(days=1)
    time = Time(
        start=frame.index[0], end=frame.index[-1] + step, step=Quantity(step.total_seconds(), "s")
    )
    opex = Opex(co2=None if co2 is None else Quantity(co2, "EUR/kg"), **(prices or PRICES))
    emissions = None if co2 is None else Emissions(CO2=CO2(electricity=Quantity(0, "g/kWh")))
    return Case(
        time=time,
        environment=environment_of(ground),
        demand=Demand(file="demand.csv", frame=frame, **services_of(frame)),
        constraints=tuple(CONSTRAINTS if limits is None else limits) + tuple(constraints),
        assumptions=Assumptions(finance=Finance(opex=opex), emissions=emissions),
    )


def plant_of_two(names=("d0", "d1")):
    """Return two doublets, a boiler and a heat user, wired by their names."""
    plant = gm.Plant("Two")
    for name in names:
        plant.add("Doublet", name=name, params=DESIGN)
    plant.add("Mixer", name="production")
    plant.add("Degasser", name="degasser")
    plant.add(
        "HeatExchanger",
        name="hx",
        params=dict(
            thermal_conductance=2e6,
            hot_nominal_pressure_drop=0,
            cold_nominal_pressure_drop=0,
            hot_nominal_mass_flow=170.0,
            cold_nominal_mass_flow=170.0,
        ),
    )
    plant.add("Splitter", name="injection")
    plant.add("GasGrid", name="grid")
    plant.add(
        "Boiler", name="boiler", params={"capacity": {"value": 40, "unit": "MW"}, "efficiency": 0.9}
    )
    plant.add("HeatingGrid", name="users", params={"return_pressure": {"value": 6, "unit": "bar"}})
    wire(plant, names)
    plant.boiler.temperature_setpoint = {"value": 100, "unit": "degC"}
    return with_values(plant)


def wire(plant, names=("d0", "d1")):
    """Connect the brine loop and the heating water, every port named."""
    first, second = names
    plant.connect(f"{first}.supply_out", "production.branch1_in")
    plant.connect(f"{second}.supply_out", "production.branch2_in")
    plant.connect("production.fluid_out", "degasser.fluid_in")
    plant.connect("degasser.liquid_out", "hx.hot_in")
    plant.connect("degasser.gas_out", "gas_out")
    plant.connect("power_in", f"{first}.power_in")
    plant.connect("power_in", f"{second}.power_in")
    plant.connect("hx.hot_out", "injection.fluid_in")
    plant.connect("injection.branch1_out", f"{first}.return_in")
    plant.connect("injection.branch2_out", f"{second}.return_in")
    plant.connect("users.return_out", "hx.cold_in")
    plant.connect("hx.cold_out", "boiler.fluid_in")
    plant.connect("grid.gas_out", "boiler.fuel_in")
    plant.connect("boiler.flue_out", "flue")
    plant.connect("boiler.loss_out", "loss")
    plant.connect("boiler.fluid_out", "users.supply_in")


def demand(*heat, freq="D"):
    """Return a demand of the given heat [W] from 2027-01-01, daily unless ``freq`` says."""
    index = pd.date_range("2027-01-01", periods=len(heat), freq=freq, tz="UTC", name="time")
    return pd.DataFrame({"heating_demand": heat}, index=index)


def at(day, hour=0):
    """Return the ISO text of an hour of a day of 2027-01."""
    return f"2027-01-{day:02d}T{hour:02d}:00:00+00:00"


def duration(value, unit="d", **fields):
    """Return the constraint that each doublet runs ``value`` ``unit`` of the period."""
    bound = {"max": (value, unit)} if "equals" not in fields else {}
    return constraint("production_flow", over="duration", when="running", **bound, **fields)


def plan_of(*heat, constraints=(), prices=None, plant=None, freq="D", **options):
    """Return the plan of ``plant_of_two`` (or ``plant``) for a daily demand of ``heat`` [W]."""
    case = case_of(demand(*heat, freq=freq), constraints, prices, **options)
    return gm.schedule(plant or plant_of_two(), case)


def _duration_checks(plant, case, results):
    """Return the checks of the duration constraint, one per doublet."""
    checks = gm.evaluate.constraints(plant, case, results)
    return [item for item in checks if item["value"].unit == "s"]


def test_doublets_run_in_order_at_the_flow_of_the_need():
    """A small need runs the first; a large one fills it and starts the second."""
    plan = plan_of(0.5 * FULL, 1.5 * FULL)
    assert plan["d0.flow"].iloc[0] == pytest.approx(150 / 3600)
    assert plan["d1.flow"].iloc[0] == 0 and not plan["d1.is_running"].iloc[0]
    assert plan["d0.flow"].iloc[1] == pytest.approx(300 / 3600)
    assert plan["d1.flow"].iloc[1] == pytest.approx(150 / 3600)


def test_below_the_minimum_a_doublet_runs_at_the_minimum():
    """Less cooling, never less flow, while it runs."""
    assert plan_of(0.01 * FULL)["d0.flow"].iloc[0] == pytest.approx(50 / 3600)


def test_the_boiler_covers_what_the_doublets_cannot():
    """The plan says how much that is, on design values."""
    assert plan_of(2.5 * FULL)["boiler_duty"].iloc[0] == pytest.approx(0.5 * FULL)


def test_the_dispatch_order_follows_the_prices():
    """Swap the two prices and the order swaps: cheap gas loads the boiler before the doublets."""
    dear_gas = {"electricity": Quantity(1, "EUR/MWh"), "gas": Quantity(100, "EUR/MWh")}
    cheap_gas = {"electricity": Quantity(100, "EUR/MWh"), "gas": Quantity(0.001, "EUR/MWh")}
    heat = 40e6 + FULL / 2
    assert plan_of(heat, prices=dear_gas)["d0.flow"].iloc[0] == pytest.approx(300 / 3600)
    assert plan_of(heat, prices=cheap_gas)["d0.flow"].iloc[0] == pytest.approx(150 / 3600)


def test_the_carbon_price_changes_the_order():
    """CO2 costs the gas boiler its emission: a high price puts the doublets first again."""
    prices = {"electricity": Quantity(1, "EUR/MWh"), "gas": Quantity(0.001, "EUR/MWh")}
    frame = demand(40e6 + FULL / 2)
    plan = gm.schedule(plant_of_two(), case_of(frame, prices=prices))
    assert plan["d0.flow"].iloc[0] == pytest.approx(150 / 3600)
    taxed = case_of(frame, prices=prices, co2=1)
    assert gm.schedule(plant_of_two(), taxed)["d0.flow"].iloc[0] == pytest.approx(300 / 3600)


def test_a_missing_price_is_named():
    """The doublets need electricity and the boiler gas."""
    for missing in PRICES:
        prices = {name: price for name, price in PRICES.items() if name != missing}
        with raises(gm.errors.ValidationError, "missing_assumption") as refused:
            plan_of(FULL, prices=prices)
        assert refused.value.path == f"assumptions.finance.opex.{missing}"


def test_the_plan_names_its_columns_after_what_they_drive():
    """Dotted control paths, ``port.field``, and the demand itself."""
    plan = plan_of(FULL)
    assert plan["heating_demand"].iloc[0] == FULL
    assert plan["users.heat_demand"].iloc[0] == FULL
    assert plan["d0.esp.frequency"].iloc[0] == float(constants.ESP_REFERENCE_FREQUENCY)
    assert plan["d0.reservoir.production_rate"].iloc[0] == pytest.approx(300 / 3600 * 1030)
    assert plan["boiler.temperature_setpoint"].iloc[0] == pytest.approx(373.15)
    assert plan["users.flow"].iloc[0] == pytest.approx(FULL / (4217.4 * 40))
    assert str(plan.index.tz) == "UTC"


def test_the_injected_brine_is_shared_as_the_doublets_produce():
    """``split_fraction`` is the share of the second outlet, the second doublet here."""
    assert plan_of(1.5 * FULL)["injection.split_fraction"].iloc[0] == pytest.approx(1 / 3)


def test_the_plan_runs_without_a_binding_and_leaves_the_plant_alone():
    """``simulate`` schedules first; the plant holds no new binding, and a plan runs the same."""
    plant = plant_of_two()
    before = plant.to_dict()
    case = case_of(demand(1.2 * FULL, 0.4 * FULL))
    frame = gm.simulate(plant, case).to_frame()
    assert plant.to_dict() == before and plant.bindings == {}
    delivered = frame["users.supply_in.enthalpy_flow"] - frame["users.return_out.enthalpy_flow"]
    assert delivered.to_numpy() == pytest.approx([1.2 * FULL, 0.4 * FULL], rel=1e-6)
    assert frame["users.unmet_demand"].to_numpy() == pytest.approx([0, 0], abs=1e-3)
    planned = gm.simulate(plant, case, plan=gm.schedule(plant, case)).to_frame()
    pd.testing.assert_frame_equal(planned, frame)


def test_a_plan_is_the_same_on_every_backend():
    """The plan runs on arrays, whatever backend is set around it."""
    plant = plant_of_two()
    case = case_of(demand(1.2 * FULL, 0.4 * FULL))
    expected = gm.schedule(plant, case)
    for backend in BACKENDS:
        with settings(backend=backend):
            plan = gm.schedule(plant, case)
        pd.testing.assert_frame_equal(plan, expected)


def test_unmet_demand_is_no_error():
    """A boiler too small leaves demand unmet, which the run reports."""
    plant = plant_of_two()
    plant.set_params("boiler", {"capacity": {"value": 1, "unit": "MW"}})
    results = gm.simulate(plant, case_of(demand(5 * FULL)))
    assert results.errors() == [] and results.to_frame()["users.unmet_demand"].iloc[0] > 0


def test_a_constraint_the_schedule_does_not_enforce_is_left_to_the_check():
    """Listed as plain data in ``attrs["check_only"]``; the flow range and cooling are enforced."""
    extra = constraint("unmet", on="heating_supply", max=(0, "W"))
    short = constraint("production_flow", min=(1, "d"), over="duration", when="running")
    plan = plan_of(FULL, constraints=[extra, short])
    assert plan.attrs["check_only"] == [extra.to_dict(), short.to_dict()]
    assert plan_of(FULL).attrs["check_only"] == []


def test_outage_steps_are_the_lowest_demand_days_and_never_overlap():
    """The first doublet takes the lowest days, the next the lowest left; heat and cold add up."""
    frame = demand(1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
    frame["cooling_demand"] = [9.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    plan = gm.schedule(plant_of_two(), case_of(frame, [duration(4)]))
    assert plan.attrs["outages"] == {"d0": [at(2), at(3)], "d1": [at(4), at(5)]}


def test_an_outage_moves_the_heat_to_the_next_doublet_and_the_boiler():
    """No flow on the outage day; every other day each doublet runs."""
    plan = plan_of(
        0.5 * FULL,
        1.5 * FULL,
        2.5 * FULL,
        3.0 * FULL,
        constraints=[duration(3)],
    )
    assert plan["d0.flow"].iloc[0] == 0 and not plan["d0.is_running"].iloc[0]
    assert plan["d1.flow"].iloc[0] == pytest.approx(150 / 3600)
    assert plan["d1.flow"].iloc[1] == 0 and plan["d0.flow"].iloc[1] == pytest.approx(300 / 3600)
    assert plan["boiler_duty"].iloc[1] == pytest.approx(0.5 * FULL)
    assert plan["injection.split_fraction"].iloc[0] == pytest.approx(1.0)


def test_a_doublet_without_a_need_still_runs_its_days():
    """Each doublet runs exactly its days: at the minimum flow when the need is covered."""
    plan = plan_of(FULL, FULL, FULL, constraints=[duration(2)])
    assert plan.attrs["outages"] == {"d0": [at(1)], "d1": [at(2)]}
    assert plan["d1.flow"].iloc[2] == pytest.approx(50 / 3600)
    assert plan["d0.is_running"].sum() == plan["d1.is_running"].sum() == 2


def test_equals_is_a_duration_too():
    """``equals`` fixes the time as ``max`` does."""
    exact = duration(0, equals=(2, "d"))
    assert plan_of(FULL, FULL, FULL, constraints=[exact]).attrs["outages"] == {
        "d0": [at(1)],
        "d1": [at(2)],
    }


def test_no_duration_gives_no_outage():
    """The outages are there to read, also without any."""
    assert plan_of(FULL).attrs["outages"] == {"d0": [], "d1": []}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (1, "more than the 3 steps"),
        (4, "expected 0 to 3"),
    ],
)
def test_a_duration_that_does_not_fit_is_refused(text, message):
    """Too many outage steps, or what is no duration."""
    with raises(gm.errors.ValidationError, "invalid_value", match=message):
        plan_of(FULL, FULL, FULL, constraints=[duration(text)])


def test_an_hourly_demand_is_planned_and_run():
    """Four days of hours: the same plan columns, one row per hour, and a run of them."""
    plant = plant_of_two()
    heat = [(0.5 + 0.1 * (hour % 24) / 24) * FULL for hour in range(96)]
    case = case_of(demand(*heat, freq="h"), [duration(90, "h")])
    plan = gm.schedule(plant, case)
    assert len(plan) == 96 and plan.index[1] - plan.index[0] == pd.Timedelta(hours=1)
    assert plan["d0.is_running"].sum() == plan["d1.is_running"].sum() == 90
    results = gm.simulate(plant, case, plan=plan)
    assert results.errors() == []
    assert [item["passed"] for item in _duration_checks(plant, case, results)] == [True, True]


def test_a_daily_demand_is_planned_and_run():
    """The same plant on days: one row per day and a run of them."""
    plant = plant_of_two()
    case = case_of(demand(FULL, 2 * FULL, 0.5 * FULL))
    plan = gm.schedule(plant, case)
    assert plan.index[1] - plan.index[0] == pd.Timedelta(days=1)
    assert gm.simulate(plant, case, plan=plan).errors() == []


def test_the_operating_time_is_the_same_share_on_hourly_and_daily_steps():
    """Two thirds of three days: 2 days of 3, or 48 hours of 72."""
    low_high = [FULL, 3 * FULL, 2 * FULL]
    daily = plan_of(*low_high, constraints=[duration(2)])
    hourly = plan_of(*np.repeat(low_high, 24), constraints=[duration(48, "h")], freq="h")
    assert daily["d0.is_running"].mean() == hourly["d0.is_running"].mean() == pytest.approx(2 / 3)


def test_a_duration_that_is_not_whole_steps_rounds_to_the_nearest_step():
    """Eight and a half hours of ten runs nine; 8.4 runs eight."""
    heat = (demand(*range(1, 11), freq="h") * FULL)["heating_demand"]
    nine = plan_of(*heat, constraints=[duration(8.5, "h")], freq="h")
    eight = plan_of(*heat, constraints=[duration(8.4, "h")], freq="h")
    assert nine["d0.is_running"].sum() == 9 and eight["d0.is_running"].sum() == 8


def split_sources():
    """Return ``d0`` feeding only a heat pump and ``d1`` only an exchanger, on one water loop."""
    plant = plant_of_two()
    spec = plant.to_dict()
    drop = ("production", "degasser", "injection")
    spec["modules"] = {name: item for name, item in spec["modules"].items() if name not in drop}
    spec["modules"]["heat_pump"] = {
        "type": "HeatPump",
        "params": {"mode": "heating", "capacity": {"value": 10, "unit": "MW"}},
    }
    spec.pop("outlets", None)
    spec["inlets"] = {"power_in": ["d0.power_in", "d1.power_in", "heat_pump.power_in"]}
    spec["outlets"] = {"flue": "boiler.flue_out", "loss": "boiler.loss_out"}
    spec["connections"] = [
        {"source": "d0.supply_out", "target": "heat_pump.source_in"},
        {"source": "heat_pump.source_out", "target": "d0.return_in"},
        {"source": "d1.supply_out", "target": "hx.hot_in"},
        {"source": "hx.hot_out", "target": "d1.return_in"},
        {"source": "users.return_out", "target": "hx.cold_in"},
        {"source": "hx.cold_out", "target": "heat_pump.sink_in"},
        {"source": "heat_pump.sink_out", "target": "boiler.fluid_in"},
        {"source": "grid.gas_out", "target": "boiler.fuel_in"},
        {"source": "boiler.fluid_out", "target": "users.supply_in"},
    ]
    built = with_values(gm.Plant.from_dict(spec))
    built.boiler.temperature_setpoint = {"value": 100, "unit": "degC"}
    built.heat_pump.temperature_setpoint = {"value": 100, "unit": "degC"}
    return built


@pytest.fixture(scope="module")
def split_run():
    """Return the plan and the run of ``split_sources``: ``d0`` off first, then ``d1``."""
    plant = split_sources()
    case = case_of(demand(0.5 * FULL, FULL, 2 * FULL), [duration(2)])
    plan = gm.schedule(plant, case)
    return plan, gm.simulate(plant, case, plan=plan).to_frame()


def test_a_heat_pump_on_the_brine_of_one_doublet_stops_with_it(split_run):
    """The wiring decides: ``d0`` off stops the heat pump, ``d1`` off does not."""
    plan, frame = split_run
    assert plan["heat_pump.is_running"].tolist() == [False, True, True]
    assert frame["heat_pump.is_running"].iloc[0] == 0 and frame["heat_pump.is_running"].iloc[1] == 1


def test_a_heat_pump_on_the_mixed_brine_keeps_running():
    """One doublet of two still feeds it; only both off stop it."""
    plant = plant_of_two()
    off = {"d0": np.array([True, True]), "d1": np.array([False, True])}
    assert _doublets_above(plant, "hx", "hot_in", off, set()) == {"d0", "d1"}


def test_the_heat_pump_loads_after_the_doublets_that_cost_less():
    """Its electricity over the COP costs more than the pumps of the doublets per heat."""
    plant = split_sources()
    plan = gm.schedule(plant, case_of(demand(25e6)))
    assert plan["d0.flow"].iloc[0] == pytest.approx(300 / 3600)
    assert 0 < plan["d1.flow"].iloc[0] < 300 / 3600


def test_a_missing_setpoint_is_named():
    """The supply temperature is a design value."""
    plant = plant_of_two()
    plant.boiler._input_values.clear()
    with raises(gm.errors.ValidationError, "invalid_design") as caught:
        gm.schedule(plant, case_of(demand(FULL)))
    assert caught.value.path == "boiler.temperature_setpoint"


def test_the_demand_needs_its_heating_column():
    """Without it there is nothing to schedule."""
    frame = demand(FULL).rename(columns={"heating_demand": "cooling_demand"})
    with raises(gm.errors.ValidationError, "missing_column"):
        gm.schedule(plant_of_two(), case_of(frame))


def test_a_finished_run_ran_the_time_of_the_constraint():
    """Two doublets, three days of four each: the plan, the run and the check agree."""
    plant = plant_of_two()
    frame = demand(0.5 * FULL, 1.5 * FULL, 2.5 * FULL, 3.0 * FULL)
    case = case_of(frame, [duration(3)])
    results = gm.simulate(plant, case)
    assert results.errors() == []
    checks = _duration_checks(plant, case, results)
    assert [item["passed"] for item in checks] == [True, True]
    assert [item["value"].value for item in checks] == [3 * 86400.0] * 2


COOLING_SIZES = {
    "heat_pump.capacity": {"value": 2, "unit": "MW"},
    "peak_boiler.capacity": {"value": 30, "unit": "MW"},
    "peak_boiler.efficiency": 0.9,
    "absorption_chiller.capacity": {"value": 3, "unit": "MW"},
    "adsorption_chiller.capacity": {"value": 1, "unit": "MW"},
    "compression_chiller.capacity": {"value": 10, "unit": "MW"},
    "absorption_chiller.thermal_cop": 0.8,
    "adsorption_chiller.thermal_cop": 0.7,
}
COOLING_INPUTS = {
    "heat_pump.temperature_setpoint": {"value": 100, "unit": "degC"},
    "peak_boiler.temperature_setpoint": {"value": 100, "unit": "degC"},
    "compression_chiller.temperature_setpoint": {"value": 20, "unit": "degC"},
    "compression_cooler.temperature_setpoint": {"value": 35, "unit": "degC"},
}


def cooling_plant(inputs=COOLING_INPUTS):
    """Return the plant with every cooling unit: only what a schedule reads is set."""
    plant = with_values(gm.plants.get("HeatingCoolingPlant"))
    plant.set_params("", COOLING_SIZES)
    plant.set_params("d0", DESIGN)
    return plant.set_inputs(inputs)


def cooling_plan(cold, heat=1e6, plant=None):
    """Return the plan of ``cooling_plant`` (or ``plant``) for one day of heat and cold [W]."""
    frame = demand(heat)
    frame["cooling_demand"] = cold
    return gm.schedule(plant or cooling_plant(), case_of(frame))


def test_a_heat_pump_and_a_compression_chiller_are_scheduled_together():
    """The plant that "expected at most one": each has its own setpoint."""
    plan = cooling_plan(8e6)
    assert plan["heat_pump.temperature_setpoint"].iloc[0] == pytest.approx(373.15)
    assert plan["compression_chiller.temperature_setpoint"].iloc[0] == pytest.approx(293.15)


def test_heat_driven_units_go_first_and_add_their_drive_heat():
    """Absorption 3 MW, adsorption 1 MW, compression the rest: 3 / 0.8 + 1 / 0.7 of heat."""
    plan = cooling_plan(8e6)
    assert plan["d0.flow"].iloc[0] == pytest.approx(
        (1e6 + 3e6 / 0.8 + 1e6 / 0.7) / (BRINE.rho_l * BRINE.cp_l * 40)
    )
    assert plan["cooling_consumer.flow"].iloc[0] == pytest.approx(8e6 / (4217.4 * 8))


def test_the_units_before_the_last_stop_where_their_share_ends():
    """28 to 20 degC over 8 MW: absorption takes 3 K, adsorption 1 K more, compression the rest."""
    plan = cooling_plan(8e6)
    assert plan["absorption_chiller.temperature_setpoint"].iloc[0] == pytest.approx(298.15)
    assert plan["adsorption_chiller.temperature_setpoint"].iloc[0] == pytest.approx(297.15)
    assert plan["compression_chiller.temperature_setpoint"].iloc[0] == pytest.approx(293.15)


def test_a_unit_with_a_poor_thermal_cop_loads_after_the_compression_chiller():
    """Its drive heat costs more per cold than the electricity of the compression: it stands."""
    plant = cooling_plant()
    plant.set_params("", {"absorption_chiller.thermal_cop": 0.01})
    plan = cooling_plan(8e6, plant=plant)
    assert plan["absorption_chiller.temperature_setpoint"].iloc[0] == pytest.approx(301.15)
    assert plan["adsorption_chiller.temperature_setpoint"].iloc[0] == pytest.approx(300.15)


def test_a_day_without_cold_takes_nothing():
    """No demand, no drive heat and no error."""
    assert cooling_plan(0.0)["cooling_consumer.flow"].iloc[0] == 0


def test_the_compression_chiller_needs_the_setpoint_of_its_cooler():
    """Its COP comes from the rejection temperature: missing, it is named."""
    inputs = {
        k: v for k, v in COOLING_INPUTS.items() if k.startswith("compression_cooler") is False
    }
    plant = cooling_plant(inputs)
    with raises(gm.errors.ValidationError, "invalid_design") as caught:
        cooling_plan(8e6, plant=plant)
    assert caught.value.path == "compression_cooler.temperature_setpoint"


def test_the_drive_water_bypasses_the_users_when_a_chiller_is_driven():
    """The splitter that sends drive water past the users divides as the heats do."""
    plan = cooling_plan(8e6)
    assert 0 < plan["drive_splitter.split_fraction"].iloc[0] < 1


def test_a_plan_states_its_units_so_a_binding_in_another_unit_does_not_misread_it():
    """A binding that reads the rate in m3/s meets a column in kg/s: the plan's unit wins."""
    plant = plant_of_two()
    plant.set_bindings("d0.reservoir", {"production_rate": {"column": "rate", "unit": "m3/s"}})
    plan = plan_of(0.5 * FULL, plant=plant).rename(columns={"d0.reservoir.production_rate": "rate"})
    assert plan.attrs["units"]["d1.reservoir.production_rate"] == "kg/s"
    plan.attrs["units"]["rate"] = "kg/s"
    flow = gm.simulate(plant, case_of(demand(0.5 * FULL)), plan=plan).get(
        "d0.reservoir", "liquid_flow"
    )["value"][0]
    assert flow == pytest.approx(150 / 3600)


def test_a_plan_keeps_the_unit_of_the_demand():
    """What the demand stated stays, and every driven column adds its own."""
    frame = demand(FULL)
    frame.attrs["units"] = {"heating_demand": "W"}
    plan = gm.schedule(plant_of_two(), case_of(frame))
    assert plan.attrs["units"]["heating_demand"] == "W"
    assert plan.attrs["units"]["d0.esp.frequency"] == "Hz"
    assert plan.attrs["units"]["boiler.temperature_setpoint"] == "K"


def test_the_doublet_heat_plant_runs_a_plan_within_its_pump_curve():
    """Its bindings read m3/s and a plan is in kg/s: the flow is what was planned, in range."""
    plant = example_plant("DoubletHeatPlant")
    wide = constraint("production_flow", min=(50, "m3/h"), max=(165, "m3/h"), when="running")
    case = case_of(demand(5e6, 3e7), limits=[wide, CONSTRAINTS[1]])
    results = gm.simulate(plant, case, on_error="record")
    assert results.errors() == []
    flows = results.get("doublet.reservoir", "liquid_flow")["value"]
    assert 50 / 3600 <= min(flows) and max(flows) == pytest.approx(165 / 3600)


@pytest.mark.parametrize(("index", "name"), [(0, "production_flow"), (1, "brine_cooling")])
def test_a_limit_the_schedule_needs_has_no_default(index, name):
    """No limit is assumed: the missing one is named."""
    limits = [item for place, item in enumerate(CONSTRAINTS) if place != index]
    with raises(gm.errors.ValidationError, "missing_value", match=name) as refused:
        gm.schedule(plant_of_two(), case_of(demand(FULL), limits=limits))
    assert refused.value.path == "constraints"


def test_a_constraint_by_role_limits_doublets_of_any_name():
    """The role, not the path, says which units a constraint limits."""
    plant = plant_of_two(("north", "south"))
    plan = gm.schedule(plant, case_of(demand(1.5 * FULL)))
    assert plan["north.flow"].iloc[0] == pytest.approx(300 / 3600)
    assert plan["south.flow"].iloc[0] == pytest.approx(150 / 3600)


def test_a_schedule_without_the_ground_names_the_path_in_the_case():
    """The plan reads the reservoir, so the missing value is named before anything else."""
    with raises(gm.errors.ValidationError, "missing_value") as caught:
        gm.schedule(plant_of_two(), case_of(demand(FULL), ground=False))
    assert caught.value.path == "environment.ground.gradient"


def test_a_profile_of_the_air_is_a_column_of_the_plan():
    """A constant air is an input of the copy; a profile is the air of each step."""
    plant = gm.Plant.from_dict(template_dict("HeatingPlant"))
    case = case_of(demand(FULL, FULL))
    air = case.environment.air.model_copy(update={"temperature": np.array([280.0, 290.0])})
    case = case.model_copy(update={"environment": case.environment.model_copy(update={"air": air})})
    plan = gm.schedule(plant, case)
    assert plan["atmosphere.temperature"].tolist() == [280.0, 290.0]
