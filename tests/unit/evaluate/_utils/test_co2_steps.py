"""The CO2 of a run, step by step."""

import pytest

import gemini as gm
from gemini.evaluate._utils import co2_steps
from gemini.units import Quantity
from tests.fixtures.cases import make_case
from tests.fixtures.costed_plants import heating_plant
from tests.fixtures.errors import raises
from tests.fixtures.result_tables import make_results

EMISSIONS = {
    "CO2": gm.case.CO2(electricity=Quantity([1e-7, 3e-7], "kg/J")),
    "CH4": gm.case.CH4(gwp=30.0),
}
RUN = make_results(
    {
        "air": {"co2_emission": [1.0, 0.0], "methane_emission": [0.0, 0.5]},
        "grid": {"net_import": [0.0, 100.0]},
    }
)


def test_each_step_has_its_own_emissions():
    """The CO2, the methane in CO2-equivalent and the electricity at the factor of the step."""
    case = make_case(count=2, emissions=EMISSIONS)
    direct, methane, equivalent, electricity = co2_steps.emissions_steps(heating_plant(), case, RUN)
    assert list(direct) == [3600.0, 0.0]
    assert list(methane) == [0.0, 1800.0] and list(equivalent) == [0.0, 54000.0]
    assert list(electricity) == pytest.approx([0.0, 3e-7 * 100.0 * 3600.0])
    total = co2_steps.emitted_steps(heating_plant(), case, RUN)
    assert list(total) == pytest.approx([3600.0, 54000.0 + 3e-7 * 360000.0])


def test_the_steps_of_a_run_without_the_columns_are_zero():
    """Nothing released, nothing drawn."""
    quiet = make_results({"heat": {"unmet_demand": [1.0, 2.0]}})
    assert list(co2_steps.released_steps(quiet, "fuel")) == [0.0, 0.0]
    assert list(co2_steps.grid_steps(heating_plant(), quiet)) == [0.0, 0.0]


def test_a_factor_is_needed_only_when_the_run_uses_it():
    """No methane and no grid electricity: no factor is asked for."""
    case = make_case(count=2)
    run = make_results({"air": {"co2_emission": [1.0, 1.0]}})
    assert list(co2_steps.emitted_steps(heating_plant(), case, run)) == [3600.0, 3600.0]
    with raises(gm.errors.ValidationError, "missing_assumption", match=r"CH4\.gwp"):
        co2_steps.emitted_steps(heating_plant(), case, RUN)
    grid = make_results({"grid": {"net_import": [5.0, 5.0]}})
    with raises(gm.errors.ValidationError, "missing_assumption", match=r"CO2\.electricity"):
        co2_steps.emitted_steps(heating_plant(), case, grid)
