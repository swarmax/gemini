"""CO2 of a run against the balance code and a hand sum."""

import pytest

import gemini as gm
from gemini._utils.jsonable import to_plain
from gemini.runtime import settings
from gemini.units import Quantity
from tests.fixtures.cases import make_case
from tests.fixtures.costed_plants import HOURS, day, heating_plant
from tests.fixtures.errors import raises
from tests.fixtures.parity import BACKENDS
from tests.fixtures.result_tables import make_results

DAY = HOURS * 3600.0
"""Seconds of the runs below."""

ELECTRICITY = make_case(emissions={"CO2": gm.case.CO2(electricity=Quantity(1e-7, "kg/J"))})
"""A case with a grid emission factor [kg/J] for runs that draw electricity."""


def test_co2_sums_the_emission_outputs_and_grid_electricity():
    """1 kg/s of CO2, 0.1 kg/s of methane and 60 W of grid electricity for a day."""
    case = make_case(
        emissions={
            "CO2": gm.case.CO2(electricity=Quantity(1e-7, "kg/J")),
            "CH4": gm.case.CH4(gwp=29.8),
        }
    )
    run = make_results(
        {
            "air": {"co2_emission": [1.0] * HOURS, "methane_emission": [0.1] * HOURS},
            "grid": {"net_import": [60.0] * HOURS},
        }
    )
    result = gm.evaluate.co2(heating_plant(), case, run)
    assert result.unit == "kg"
    assert to_plain(result.parts["direct"]) == {"value": DAY, "unit": "kg"}
    assert result.parts["methane"].value == pytest.approx(0.1 * DAY)
    assert to_plain(result.parts["grid_energy"]) == {"value": 60.0 * DAY, "unit": "J"}
    assert result.parts["electricity"].value == pytest.approx(60.0 * DAY * 1e-7)
    assert result.value == pytest.approx(DAY + 0.1 * DAY * 29.8 + 60.0 * DAY * 1e-7)
    assert to_plain(result.parts["window"]) == {"value": DAY, "unit": "s"}


def test_the_methane_factor_is_an_assumption():
    """``emissions.CH4.gwp`` scales the methane released."""
    run = make_results({"air": {"methane_emission": [1.0]}})
    case = make_case(count=1, emissions={"CH4": gm.case.CH4(gwp=10.0)})
    result = gm.evaluate.co2(heating_plant(), case, run)
    assert result.value == pytest.approx(36000.0)


def test_methane_without_a_gwp_is_refused():
    """Releasing methane with no ``emissions.CH4.gwp`` names what to give."""
    run = make_results({"air": {"methane_emission": [1.0]}})
    with raises(
        gm.errors.ValidationError,
        "missing_assumption",
        match=r"assumptions\.emissions\.CH4\.gwp",
    ):
        gm.evaluate.co2(heating_plant(), make_case(count=1), run)


def test_a_grid_factor_that_is_a_profile_follows_the_steps():
    """The electricity drawn only in the dear half of the day is charged at the dear factor."""
    run = make_results({"grid": {"net_import": [0.0] * 12 + [100.0] * 12}})
    factor = Quantity([1e-7] * 12 + [3e-7] * 12, "kg/J")
    case = make_case(emissions={"CO2": gm.case.CO2(electricity=factor)})
    result = gm.evaluate.co2(heating_plant(), case, run)
    assert result.value == pytest.approx(3e-7 * 100.0 * 12 * 3600.0)


def test_fuel_alone_emits_nothing_of_its_own():
    """Emissions come from the composition through the modules, not from a fuel factor."""
    run = make_results({"boiler": {"fuel": [500.0]}})
    assert gm.evaluate.co2(heating_plant(), make_case(), run).value == 0
    assert (
        gm.evaluate.co2(heating_plant(), make_case(), run).parts["fuel_energy"].value
        == 500.0 * 3600
    )


def test_the_energies_of_a_run_do_not_depend_on_the_backend():
    """Economics reads the arrays of a finished run under any backend."""
    run = day(electricity=100.0, generated=40.0, fuel=1000.0)
    expected = gm.evaluate.co2(heating_plant(), ELECTRICITY, run)
    for backend in BACKENDS:
        with settings(backend=backend):
            assert gm.evaluate.co2(heating_plant(), ELECTRICITY, run) == expected


def test_a_surplus_of_generation_earns_no_credit():
    """Generation above consumption draws no grid electricity, and the factor is not needed."""
    result = gm.evaluate.co2(
        heating_plant(), make_case(), day(electricity=10.0, generated=50.0, fuel=0.0)
    )
    assert result.parts["grid_energy"].value == 0.0
    assert result.value == 0.0


def test_grid_electricity_without_a_factor_is_refused():
    """Drawing electricity with no ``electricity_emission_factor`` names what to give."""
    with raises(
        gm.errors.ValidationError,
        "missing_assumption",
        match=r"assumptions\.emissions\.CO2\.electricity",
    ):
        gm.evaluate.co2(heating_plant(), make_case(), day())


def test_a_run_without_fuel_or_electricity_emits_nothing():
    """A run without those columns draws nothing."""
    quiet = make_results({"heat": {"unmet_demand": [1.0, 2.0]}})
    result = gm.evaluate.co2(heating_plant(), make_case(), quiet)
    assert result.parts["fuel_energy"].value == 0.0 and result.parts["grid_energy"].value == 0.0
