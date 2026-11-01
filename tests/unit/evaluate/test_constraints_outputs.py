"""Constraints on what a unit delivers and on the plant as a whole, against hand-made runs."""

import pytest

import gemini as gm
from gemini.units import Quantity
from tests.fixtures.cases import make_case
from tests.fixtures.errors import raises
from tests.fixtures.result_tables import make_results

BASE = 1e6
GAINS = [2e3, 5e3, 3e3, 4e3]
RUNNING = [1.0, 1.0, 0.0, 1.0]
BOUGHT = [1e3, 4e3, 2e3, 3e3]
BOUNDS = ("min", "max", "equals")


def plant():
    """Return the plant with a heat pump, a compression chiller and the two grids."""
    return gm.plants.get("HeatingHeatPumpCoolingPlant")


def run(**extra):
    """Return a run: the heat pump heats by ``GAINS`` [W], and the grid sells nothing."""
    columns = {
        "heat_pump": {
            "sink_in.enthalpy_flow": [BASE] * 4,
            "sink_out.enthalpy_flow": [BASE + gain for gain in GAINS],
            "source_in.enthalpy_flow": [BASE] * 4,
            "source_out.enthalpy_flow": [BASE - gain for gain in GAINS],
            "operating": RUNNING,
        },
        "electricity_grid": {"net_import": BOUGHT, "operating": [1.0] * 4},
    }
    return make_results(columns | extra)


def verdicts(*constraints, results=None):
    """Return the checks of ``constraints`` on the plant."""
    case = make_case(count=4, constraints=list(constraints))
    return gm.evaluate.constraints(plant(), case, results or run())


def limit(role, quantity, **kwargs):
    """Return a constraint with bounds in watts."""
    bounds = {name: Quantity(value, "W") for name, value in kwargs.items() if name in BOUNDS}
    rest = {name: value for name, value in kwargs.items() if name not in BOUNDS}
    return gm.case.Constraint(on=role, quantity=quantity, **bounds, **rest)


def test_a_heat_output_over_its_limit_fails_with_name_value_and_limit():
    """The heat pump gives 5 kW at its peak; the limit is 4 kW."""
    (found,) = verdicts(limit("heat_pump", "heat_output", max=4e3))
    assert found["name"] == "heat_pump.heat_output" and found["passed"] is False
    assert found["unit_path"] == "heat_pump" and found["value"].value == 5e3
    assert found["limit"].value == 4e3 and found["worst_step"] == "2024-01-01T01:00:00+00:00"
    (found,) = verdicts(limit("heat_pump", "heat_output", max=6e3))
    assert found["passed"] is True


def test_a_cold_output_is_read_on_the_source_side_of_a_compression_chiller():
    """The heat pump of the plant is a heat pump; the chiller role finds none of the same name."""
    found = verdicts(limit("chiller", "cold_output", max=1e9), results=run())
    assert [item["unit_path"] for item in found] == ["compression_chiller"]
    assert found[0]["passed"] is None and "no_value" in found[0]["value"].reason


def test_the_cold_output_of_a_heat_pump_in_cooling_mode_is_its_source_side():
    """A heat pump whose source reaches the cooling grid takes cold out of its source circuit."""
    results = run(
        compression_chiller={
            "source_in.enthalpy_flow": [BASE] * 4,
            "source_out.enthalpy_flow": [BASE - gain for gain in GAINS],
            "operating": RUNNING,
        }
    )
    (found,) = verdicts(limit("chiller", "cold_output", max=4e3), results=results)
    assert found["passed"] is False and found["value"].value == 5e3


def test_plant_figures_are_read_from_the_edge_modules():
    """The bought electricity is the grid import, the plant is the unit with path ''."""
    (found,) = verdicts(limit("plant", "electricity_bought", max=3e3))
    assert found["unit_path"] == "" and found["name"] == "electricity_bought"
    assert found["passed"] is False and found["value"].value == 4e3
    (found,) = verdicts(limit("plant", "electricity_bought", max=5e3))
    assert found["passed"] is True


def test_a_plant_without_a_gas_grid_figure_gives_no_value():
    """The run holds no gas column: undecided, not a crash."""
    (found,) = verdicts(limit("plant", "gas_bought", max=1.0))
    assert found["passed"] is None and "no_value" in found["value"].reason


@pytest.mark.parametrize(
    ("over", "bounds", "value"),
    [
        ("sum", {"max": 1e3}, 10e3),
        ("mean", {"max": 1e3}, 2.5e3),
        ("max", {"max": 1e3}, 4e3),
        ("min", {"min": 5e3}, 1e3),
    ],
)
def test_every_aggregate_reads_a_new_quantity(over, bounds, value):
    """The figure of the run, judged against a bound it breaks."""
    (found,) = verdicts(limit("plant", "electricity_bought", over=over, **bounds))
    assert found["passed"] is False and found["value"].value == value
    assert found["worst_step"] is None


def test_duration_counts_the_hours_a_quantity_is_over_its_bound():
    """The heat pump runs three of four hours."""
    constraint = gm.case.Constraint(
        on="heat_pump",
        quantity="heat_output",
        over="duration",
        when="running",
        max=Quantity(2, "h"),
    )
    (found,) = verdicts(constraint)
    assert found["passed"] is False and found["value"].value == 3 * 3600.0


def test_when_running_leaves_out_the_steps_without_flow():
    """The idle third step has the lowest output; running steps start at 2 kW."""
    (found,) = verdicts(limit("heat_pump", "heat_output", over="min", min=2.5e3, when="running"))
    assert found["passed"] is False and found["value"].value == 2e3
    (found,) = verdicts(limit("heat_pump", "heat_output", over="min", min=2.5e3))
    assert found["value"].value == 2e3


def test_co2_is_the_mass_of_each_step_and_sums_to_the_co2_of_the_run():
    """The sum over the steps of the plant's co2 is ``gm.evaluate.co2``."""
    emissions = {"CO2": gm.case.CO2(electricity=Quantity(1e-7, "kg/J"))}
    constraint = gm.case.Constraint(on="plant", quantity="co2", over="sum", max=Quantity(1, "kg"))
    case = make_case(count=4, constraints=[constraint], emissions=emissions)
    results = run()
    (found,) = gm.evaluate.constraints(plant(), case, results)
    total = gm.evaluate.co2(plant(), case, results).value
    assert found["value"].unit == "kg" and found["value"].value == pytest.approx(total)
    assert found["passed"] == (total <= 1.0)


def test_the_plant_role_is_listed():
    """The table and the capabilities name it."""
    assert gm.case.roles()["plant"] == ["electricity_bought", "gas_bought", "heat_surplus", "co2"]
    assert all("plant" in item["roles"] for item in gm.plants.capabilities().values())


def test_a_wrong_quantity_of_the_plant_is_refused():
    """Closed table."""
    with raises(gm.errors.ValidationError, "invalid_value"):
        gm.case.Constraint(on="plant", quantity="cop", max=Quantity(1, "W"))


def test_a_figure_the_run_lacks_gives_no_value_also_when_running():
    """The empty series meets the flags of the steps: undecided, not a crash."""
    (found,) = verdicts(limit("plant", "gas_bought", max=1.0, when="running"))
    assert found["passed"] is None and "no_value" in found["value"].reason
