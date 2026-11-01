"""Unit conversion round trips and historical scale factors."""

from types import SimpleNamespace

import numpy as np
import pytest

from gemini import units
from gemini.errors import ValidationError
from tests.fixtures.errors import raises


@pytest.mark.parametrize(
    "forward,inverse",
    [
        ("bar_to_pa", "pa_to_bar"),
        ("c_to_k", "k_to_c"),
        ("m3h_to_m3s", "m3s_to_m3h"),
        ("md_to_m2", "m2_to_md"),
        ("m3s_to_bbl_per_day", "bbl_per_day_to_m3s"),
        ("ft_head_to_pa", "pa_to_ft_head"),
        ("bhp_to_w", "w_to_bhp"),
        ("m_to_ft", "ft_to_m"),
        ("kgm3_to_lbmft3", "lbmft3_to_kgm3"),
        ("pas_to_cp", "cp_to_pas"),
        ("nm_to_dyne_cm", "dyne_cm_to_nm"),
        ("index_to_si", "index_from_si"),
        ("inch_to_m", "m_to_inch"),
        ("m_to_mm", "mm_to_m"),
        ("m3s_to_m3day", "m3day_to_m3s"),
        ("kgm3_to_mgl", "mgl_to_kgm3"),
        ("pa_to_gpa", "gpa_to_pa"),
        ("rad_to_deg", "deg_to_rad"),
    ],
)
def test_round_trip(forward, inverse):
    """Conversions round-trip a nontrivial input without changing its physical value."""
    assert getattr(units, inverse)(getattr(units, forward)(3.7)) == pytest.approx(3.7)


def test_known_scales():
    """Pressure, temperature and time scales match SI definitions and the legacy year."""
    assert units.bar_to_pa(1) == 100000
    assert units.c_to_k(0) == 273.15
    assert units.SECONDS_PER_YEAR == 31557600


def test_to_si_scales_offsets_and_unknown_units():
    """Raw data units convert with their scale and offset; unknown units name the valid ones."""
    assert units.to_si(2, "bar") == 2e5
    assert units.to_si(1, "barg") == 201325
    assert units.to_si(25, "°C") == 298.15
    assert units.to_si(36, "t/h") == 10
    with raises(ValidationError, "invalid_unit", match="'barr'.*did you mean 'bar'"):
        units.to_si(1, "barr")


def test_convert_between_units_of_one_dimension():
    """Conversion goes through SI and rejects units of another dimension."""
    assert units.convert(2e5, "Pa", "bar") == 2
    assert units.convert(300, "K", "degC") == pytest.approx(26.85)
    assert units.convert(1, "m3/s", "m3/h") == 3600
    with raises(ValidationError, "invalid_unit", match="'K'.*'Pa'.*'bar'"):
        units.convert(1, "bar", "K")


def test_convert_identity_for_every_declared_unit():
    """Every unit a quantity alias declares converts to itself."""
    for unit in ("W/K", "Hz", "kg/m3", "Pa.s", "m2", "m/s", "currency", "currency/yr"):
        assert units.convert(5.0, unit, unit) == 5.0
    assert units.convert(36.0, "currency/h", "currency/s") == pytest.approx(0.01)
    assert units.convert(5.0, "stages", "stages") == 5.0


def test_difference_quantities_ignore_offsets():
    """A temperature or pressure difference converts by scale only (10 K is 10 degC)."""
    assert units.convert(10.0, "K", "degC", quantity="temperature_difference") == 10.0
    assert units.convert(1e5, "Pa", "barg", quantity="pressure_difference") == 1.0
    assert (
        units.value_in_si(
            {"value": 5, "unit": "degC"}, "K", "dT", quantity="temperature_difference"
        )
        == 5.0
    )
    assert (
        units.value_in_si({"value": 2, "unit": "barg"}, "Pa", "dp", quantity="pressure_difference")
        == 2e5
    )
    assert (
        units.value_in_si({"value": 5, "unit": "degC"}, "K", "T", quantity="temperature") == 278.15
    )


def test_value_in_si_converts_quantities_and_their_dicts():
    """A Quantity and its dict convert; a plain number or another value passes unchanged."""
    assert units.value_in_si({"value": 1.5e3, "unit": "bar"}, "Pa") == 1.5e8
    assert units.value_in_si(units.Quantity(3, "ft"), "m") == pytest.approx(0.9144)
    assert units.value_in_si(12.0, "m") == 12.0
    assert units.value_in_si(units.Quantity([1, 2], "km"), "m").tolist() == [1000.0, 2000.0]
    with raises(
        ValidationError, "invalid_unit", match="plant.length: unit = 'bar'; expected one of"
    ):
        units.value_in_si({"value": 12, "unit": "bar"}, "m", "plant.length")


@pytest.mark.parametrize("text", ["12", "12 m", "abc", " "])
def test_unit_text_is_refused_and_shows_the_dict_form(text):
    """A text for a field with a unit is no quantity, whatever it says."""
    with raises(
        ValidationError, "invalid_value", match="plant.length.*'value': 150, 'unit': 'm3/h'"
    ):
        units.value_in_si(text, "m", "plant.length")


def test_a_wrong_dimension_lists_the_units_of_the_field():
    """The message names the field and the units it accepts."""
    with raises(ValidationError, "invalid_unit", match="reservoir.flow.*m3/h.*m3/s") as caught:
        units.value_in_si(units.Quantity(300, "m"), "m3/s", "reservoir.flow", "volume_flow")
    assert "'m'" in str(caught.value)


def test_value_in_si_without_declared_unit_keeps_the_value():
    """A declaration without a unit keeps text such as '12 m' or '2 stages' unchanged."""
    assert units.value_in_si("12 m", None) == "12 m"
    assert units.value_in_si("2 stages", None) == "2 stages"


def test_value_in_si_only_converts_quantity_objects():
    """Objects that merely carry value and unit attributes are not quantities."""
    duck = SimpleNamespace(value=3, unit="ft")
    assert units.value_in_si(duck, "m") is duck


def test_duration_and_productivity_index_field_units():
    """Durations accept minutes, hours and days; productivity indices accept m3/h/bar."""
    assert units.convert(1.5, "h", "s") == 5400
    assert units.convert(2, "d", "min") == 2880
    assert units.convert(36, "m3/h/bar", "m3/s/Pa") == pytest.approx(1e-7)


@pytest.mark.parametrize(
    ("unit", "quantity"),
    [("bar", "pressure"), ("°C", "temperature"), ("°C", "temperature_difference"), ("m3/h", None)],
)
def test_si_conversion_gives_the_bits_of_to_si_on_arrays(unit, quantity):
    """One scale and offset convert a whole column to exactly the scalar results."""
    values = np.array([0.1, 3.7, 12.3456789, -4.2e-3, 1e5])
    scale, offset = units.si_conversion(unit, quantity)
    expected = [units.to_si(value, unit, quantity) for value in values.tolist()]
    assert (values * scale + offset).tolist() == expected
    assert units.array_to_si(values, unit, quantity).tolist() == expected
    with raises(ValidationError, "invalid_unit", match="units.si_conversion"):
        units.si_conversion("furlong")


@pytest.mark.parametrize(
    ("unit", "value", "expected"),
    [
        ("km", 2.5, 2500.0),
        ("mm", 4.0, 0.004),
        ("in", 2.0, 0.0508),
        ("kPa", 300.0, 3e5),
        ("MPa", 1.2, 1.2e6),
        ("rpm", 3000.0, 50.0),
        ("degC", 20.0, 293.15),
        ("m3/h", 36.0, 0.01),
        ("MW", 2.0, 2e6),
        ("kW", 5.0, 5000.0),
        ("bar(g)", 1.0, 201325.0),
    ],
)
def test_public_units_convert_to_si(unit, value, expected):
    """The units the backend accepts convert to SI, and rpm is one sixtieth of a hertz."""
    assert units.to_si(value, unit) == pytest.approx(expected, rel=1e-15)
    assert units.convert(value, unit, units.si_unit(unit)) == pytest.approx(expected, rel=1e-15)


def test_gauge_pressure_spellings_are_one_entry():
    """bar(g) and barg are the same gauge convention."""
    assert units.to_si(2.5, "bar(g)") == units.to_si(2.5, "barg")


def test_names_list_every_unit_or_those_of_one_quantity():
    """Without a quantity every unit is listed; with one, the units of its SI unit."""
    assert "rpm" in units.names() and units.names() == sorted(units.names())
    assert {"Pa", "bar", "bar(g)", "kPa", "MPa"} <= set(units.names("pressure"))
    assert "m3/h" in units.names("volume_flow") and "bar" not in units.names("volume_flow")
    with raises(ValidationError, "unknown_name", match="did you mean 'pressure'") as caught:
        units.names("pressur")
    assert caught.value.suggestions[0] == "pressure"


def test_unit_is_generated_from_the_table():
    """Every unit of the table is a member, and a member is its string."""
    assert {str(member) for member in units.Unit} == set(units.names())
    assert units.Unit.M3_PER_H == "m3/h" and units.Unit.DEG_C == "degC"
    assert units.Unit.EUR_PER_MWH == "EUR/MWh" and units.Unit.PERCENT_PER_YR == "%/yr"
    assert units.Unit.G_PER_KWH == "g/kWh" and units.Unit.EUR_PER_W_PER_K == "EUR/(W/K)"


def test_a_quantity_round_trips_through_its_dict():
    """``to_dict`` and ``from_dict`` give the same quantity, for a number and an array."""
    for quantity in (units.Quantity(2500, "m"), units.Quantity(np.array([1.0, 2.5]), "m3/h")):
        assert units.Quantity.from_dict(quantity.to_dict()) == quantity
    assert units.Quantity(3, "ft").to_dict() == {"value": 3, "unit": "ft"}
    assert isinstance(units.Quantity(3, "ft").unit, units.Unit)


def test_a_quantity_compares_si_values():
    """100 bar equals 1e7 Pa."""
    assert units.Quantity(100, "bar") == units.Quantity(1e7, "Pa")
    assert units.Quantity(100, "bar") != units.Quantity(100, "Pa")
    assert units.Quantity(1, "d").si == 86400.0


def test_to_converts_across_offset_units_and_differences():
    """A degC or a barg value carries an offset, a difference does not."""
    assert units.Quantity(20, "degC").to("K").value == pytest.approx(293.15)
    assert units.Quantity(293.15, "K").to("degC").value == pytest.approx(20.0)
    assert units.Quantity(1, "barg").to("bar").value == pytest.approx(2.01325)
    assert units.Quantity(10, "K").to("degC", "temperature_difference").value == 10.0
    assert units.Quantity(36, "m3/h").to("m3/s").value == pytest.approx(0.01)
    assert units.Quantity(300, "g/kWh").to("kg/J").value == pytest.approx(300e-3 / 3.6e6)
    assert units.Quantity(60, "EUR/MWh").to("EUR/kWh").value == pytest.approx(0.06)
    with raises(ValidationError, "invalid_unit", match="'K'.*'Pa'"):
        units.Quantity(1, "bar").to("K")


def test_an_unknown_unit_or_a_wrong_dict_is_refused():
    """A unit that is not in the table, or a dict that is not a quantity."""
    with raises(ValidationError, "invalid_unit", match="'furlong'"):
        units.Quantity(3, "furlong")
    for data in ({"value": 3}, {"value": 3, "unit": "m", "extra": 1}, "3 m", [3, "m"]):
        with raises(ValidationError, "invalid_value", match="'value': 150"):
            units.Quantity.from_dict(data)


def test_no_text_parser_is_left():
    """Unit text is read nowhere: ``parse`` and ``split_quantity`` are gone."""
    assert not hasattr(units, "parse") and not hasattr(units, "split_quantity")


def test_reports_print_in_their_own_units():
    """Energy, mass and per-year units a report prints with convert from the SI of a result."""
    assert units.Quantity(3.6e12, "J").to("GWh").value == pytest.approx(1.0)
    assert units.Quantity(2e6, "kWh").to("MWh").value == pytest.approx(2000.0)
    assert units.Quantity(5e6, "kg").to("kt").value == pytest.approx(5.0)
    assert units.Quantity(2e6, "kg/yr").to("t/yr").value == pytest.approx(2000.0)
    assert units.Quantity(7.2e12, "J/yr").to("GWh/yr").value == pytest.approx(2.0)
    assert units.Unit.GWH == "GWh" and units.Unit.T_PER_YR == "t/yr"


def test_a_cost_per_volume_converts_to_currency_per_m3():
    """EUR/m3 is the unit of a storage factor and is SI already."""
    assert units.Quantity(40, "EUR/m3").si == 40
    assert units.fits("EUR/m3", "money_per_volume")
