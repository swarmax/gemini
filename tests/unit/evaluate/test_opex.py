"""Annual operating cost against the fixed shares, the prices and hand sums."""

import pytest

import gemini as gm
from gemini.evaluate._utils import cost
from gemini.units import SECONDS_PER_YEAR, Quantity
from tests.fixtures.cases import make_case
from tests.fixtures.costed_plants import HOURS, day, heating_cooling_plant, heating_plant
from tests.fixtures.errors import raises
from tests.fixtures.result_tables import make_results

GRID_PER_YEAR = 100.0 * SECONDS_PER_YEAR
"""Grid electricity [J/year] of 100 W drawn all year."""


def priced(fixed=None, capex=True, **prices):
    """Return a case whose finance holds ``prices`` [currency/J, currency/kg] and the fixed shares.

    The degasser costs 1000 and its fixed opex is 1 %/yr unless ``fixed`` says otherwise.
    """
    shares = {"degasser": Quantity(1, "%/yr")} if fixed is None else fixed
    opex = {name: Quantity(price, _unit(name)) for name, price in prices.items()}
    finance = {"opex": gm.case.Opex(fixed=shares or None, **opex)}
    if capex:
        finance["capex"] = gm.case.Capex(degasser=Quantity(1000.0, "currency"))
    return make_case(finance=finance)


def _unit(name):
    """Return the unit of a price: per joule, or per kilogram for a material."""
    return "currency/J" if name in ("electricity", "gas") else "currency/kg"


def test_opex_adds_the_fixed_share_and_the_energy_bill():
    """1 % of a capex of 1000 is 10 a year; the electricity at 2e-8 per joule."""
    result = gm.evaluate.opex(heating_plant(), priced(electricity=2e-8), day())
    components = {name: item.value for name, item in result.parts["components"].items()}
    assert {item.unit for item in result.parts["components"].values()} == {"currency/yr"}
    assert components["fixed"] == pytest.approx(10.0)
    assert components["electricity"] == pytest.approx(2e-8 * GRID_PER_YEAR, rel=1e-12)
    assert components["fuel"] == 0.0
    assert "co2" not in components and "variable" not in components
    assert result.value == pytest.approx(sum(components.values()), rel=1e-12)
    assert result.unit == "currency/yr"


def test_fixed_opex_is_listed_by_kind():
    """Each kind of equipment has its share of its capex."""
    result = gm.evaluate.opex(heating_plant(), priced(electricity=2e-8), day())
    assert {kind: item.value for kind, item in result.parts["fixed_by_kind"].items()} == {
        "degasser": pytest.approx(10.0)
    }


def test_each_kind_has_its_own_share():
    """A degasser at 1 %/yr of 1000 and a flare at 3 %/yr of 2000."""
    finance = {
        "capex": gm.case.Capex(
            degasser=Quantity(1000.0, "currency"), flare=Quantity(2000.0, "currency")
        ),
        "opex": gm.case.Opex(
            fixed={"degasser": Quantity(1, "%/yr"), "flare": Quantity(3, "%/yr")},
            electricity=Quantity(0.0, "currency/J"),
        ),
    }
    result = gm.evaluate.opex(heating_cooling_plant(), make_case(finance=finance), day(cold=1.0))
    fixed = {kind: item.value for kind, item in result.parts["fixed_by_kind"].items()}
    assert fixed == {"degasser": pytest.approx(10.0), "flare": pytest.approx(60.0)}
    assert result.parts["components"]["fixed"].value == pytest.approx(70.0)


def test_a_share_the_case_lacks_is_missing_assumption_naming_the_kind():
    """The degasser has a capex but no fixed share: the user is asked."""
    with raises(
        gm.errors.ValidationError,
        "missing_assumption",
        match=r"assumptions\.finance\.opex\.fixed\.degasser",
    ):
        gm.evaluate.opex(heating_plant(), priced(fixed={}, electricity=2e-8), day())


def test_opex_needs_the_price_of_an_energy_the_run_draws():
    """Electricity is drawn but has no price: the user is asked, not guessed for."""
    with raises(
        gm.errors.ValidationError,
        "missing_assumption",
        match=r"assumptions\.finance\.opex\.electricity",
    ):
        gm.evaluate.opex(heating_plant(), priced(), day())


def test_opex_without_equipment_reports_only_the_bill():
    """No equipment: the value is null and says why; the bill is still given."""
    result = gm.evaluate.opex(
        heating_plant(costed=False), priced(electricity=2e-8), day(), on_error="record"
    )
    assert result.value is None and result.reason == cost.NO_COST
    assert result.parts["components"]["electricity"].value == pytest.approx(
        2e-8 * GRID_PER_YEAR, rel=1e-12
    )


def test_a_price_profile_bills_the_hours_that_draw_power():
    """Power drawn only in the dear half of the day is billed at the dear price."""
    run = make_results({"grid": {"net_import": [0.0] * 12 + [100.0] * 12}})
    profile = priced(electricity=[1e-8] * 12 + [3e-8] * 12)
    result = gm.evaluate.opex(heating_plant(costed=False), profile, run, on_error="record")
    assert result.parts["components"]["electricity"].value == pytest.approx(
        3e-8 * 100.0 * SECONDS_PER_YEAR / 2
    )


def test_a_co2_price_adds_one_component_per_year():
    """1 kg/s of CO2 for a day, scaled to a year, at 0.5 per kg."""
    run = make_results({"air": {"co2_emission": [1.0] * HOURS}})
    result = gm.evaluate.opex(heating_plant(costed=False), priced(co2=0.5), run, on_error="record")
    assert result.parts["components"]["co2"].value == pytest.approx(0.5 * SECONDS_PER_YEAR)
    assert result.parts["components"]["co2"].unit == "currency/yr"
    without = gm.evaluate.opex(heating_plant(costed=False), priced(), run, on_error="record")
    assert "co2" not in without.parts["components"]


def test_a_co2_price_profile_follows_the_steps():
    """CO2 emitted only in the dear half of the day is billed at the dear price."""
    run = make_results({"air": {"co2_emission": [0.0] * 12 + [1.0] * 12}})
    profile = priced(co2=[0.1] * 12 + [0.4] * 12)
    result = gm.evaluate.opex(heating_plant(costed=False), profile, run, on_error="record")
    assert result.parts["components"]["co2"].value == pytest.approx(
        0.4 * 1.0 * SECONDS_PER_YEAR / 2
    )
