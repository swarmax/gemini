"""The unit in which a metric is shown in a table."""

import pytest

import gemini as gm
from gemini.evaluate._utils.display import display_units, in_unit
from tests.fixtures.errors import raises


def test_a_metric_is_shown_in_its_unit_or_the_one_given():
    """Metrics without a display unit are left out."""
    assert display_units(["lcts", "co2", "cop"]) == {"lcts": "EUR/MWh", "co2": "kt"}
    assert display_units(["lcts"], {"lcts": "EUR/kWh"}) == {"lcts": "EUR/kWh"}


def test_a_number_is_converted_from_si():
    """1 currency/J is 3.6e9 EUR/MWh; 1e6 kg is 1 kt."""
    assert in_unit("lcts", 1.0, "EUR/MWh") == pytest.approx(3.6e9)
    assert in_unit("co2", 1e6, "kt") == pytest.approx(1.0)
    assert in_unit("co2", None, "kt") is None


def test_a_unit_that_does_not_fit_is_refused():
    """A name that is not a shown metric; a unit of another dimension."""
    with raises(gm.errors.ValidationError, "invalid_value", match="units.cop"):
        display_units(["lcts"], {"cop": "kt"})
    with raises(gm.errors.ValidationError, "invalid_unit"):
        display_units(["co2"], {"co2": "MWh"})


def test_the_display_unit_of_an_si_unit_comes_from_the_one_table():
    """Flow in m3/h, temperature in degC, energy in MWh."""
    from gemini.evaluate._utils.display import by_si_unit, shown
    from gemini.units import Quantity

    table = by_si_unit()
    assert table["m3/s"] == "m3/h" and table["K"] == "degC" and table["J"] == "MWh"
    assert shown({"t": [Quantity(293.15, "K")]}, table)["t"][0].value == pytest.approx(20.0)
