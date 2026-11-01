"""``gm.case.Assumptions``: finance and emissions, with no default."""

import pytest

import gemini as gm
from gemini.case._utils.kinds import EQUIPMENT_KINDS
from gemini.units import Quantity
from tests.fixtures.errors import raises


def test_the_capex_has_one_factor_per_equipment_kind():
    """The fields of ``Capex`` are the closed list of kinds, each with its dimension."""
    assert list(gm.case.Capex.model_fields) == list(EQUIPMENT_KINDS)
    capex = gm.case.Capex(
        drilling=Quantity(1239, "EUR/m"),
        heat_exchanger=Quantity(0.5, "EUR/(W/K)"),
        degasser=Quantity(1e6, "EUR"),
        ice_storage=Quantity(40, "EUR/m3"),
    )
    assert capex.drilling == 1239 and capex.heat_exchanger == 0.5 and capex.ice_storage == 40
    assert capex.boiler is None


def test_a_factor_of_another_basis_is_invalid_unit():
    """A boiler is priced per W, not per metre."""
    with raises(gm.errors.ValidationError, "invalid_unit"):
        gm.case.Capex(boiler=Quantity(100, "EUR/m"))


def test_the_fixed_opex_is_a_share_per_year_by_kind():
    """2 %/yr is 0.02 per year; a kind outside the list is unknown."""
    opex = gm.case.Opex(fixed={"heat_pump": Quantity(2, "%/yr")})
    assert opex.fixed == {"heat_pump": pytest.approx(0.02)}
    assert opex.to_dict()["fixed"]["heat_pump"]["unit"] == "1/yr"
    with raises(gm.errors.ValidationError, "unknown_name"):
        gm.case.Opex(fixed={"pumps": Quantity(2, "%/yr")})


def test_prices_are_a_constant_or_a_profile_in_si():
    """100 EUR/MWh is currency per joule; a list is a profile."""
    opex = gm.case.Opex(electricity=Quantity(100, "EUR/MWh"), co2=Quantity([80.0, 90.0], "EUR/t"))
    assert opex.electricity == pytest.approx(100 / 3.6e9)
    assert list(opex.co2) == pytest.approx([0.08, 0.09])


def test_the_finance_values():
    """Lifetime in seconds, rate and share dimensionless, share at most 1."""
    finance = gm.case.Finance(
        currency="EUR",
        discount_rate=0.05,
        lifetime=Quantity(25, "yr"),
        price_year=2015,
        allocation=gm.case.Allocation(heat_cost_share=0.8),
    )
    assert finance.lifetime == pytest.approx(25 * 31557600.0)
    assert finance.to_dict()["discount_rate"] == 0.05
    with raises(gm.errors.ValidationError, "out_of_bounds"):
        gm.case.Allocation(heat_cost_share=1.5)
    with raises(gm.errors.ValidationError, "invalid_unit"):
        gm.case.Finance(discount_rate=Quantity(5, "%/yr"))


def test_the_emissions_are_by_species():
    """CO2 per electricity energy and the methane warming potential."""
    emissions = gm.case.Emissions(
        CO2=gm.case.CO2(electricity=Quantity(300, "g/kWh")), CH4=gm.case.CH4(gwp=29.8)
    )
    assert emissions.CO2.electricity == pytest.approx(300e-3 / 3.6e6)
    assert emissions.CH4.gwp == 29.8
    with raises(gm.errors.ValidationError, "unknown_name"):
        gm.case.Emissions(N2=gm.case.CH4(gwp=1))


def test_nothing_is_given_by_default():
    """An empty assumptions holds nothing."""
    assert gm.case.Assumptions().to_dict() == {}
    assert gm.case.Finance().capex is None
