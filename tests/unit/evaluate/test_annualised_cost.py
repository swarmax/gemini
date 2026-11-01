"""Annualised cost against the closed-form annuity."""

import pytest

import gemini as gm
from gemini._utils.jsonable import to_plain
from gemini.units import SECONDS_PER_YEAR
from tests.fixtures.costed_plants import day, heating_plant
from tests.fixtures.errors import raises
from tests.fixtures.result_tables import make_problem

PRICES = make_problem(
    assumptions=gm.Assumptions(prices={"electricity": gm.units.Quantity(2e-8, "currency/J")})
)
HEAT = 1000.0 * SECONDS_PER_YEAR
OPEX = 10.0 + 1e-9 * HEAT + 2e-8 * 100.0 * SECONDS_PER_YEAR
"""Yearly cost of the heating plant under ``PRICES``: fixed, variable and electricity."""


def test_the_annualised_cost_is_capex_over_the_annuity_plus_opex():
    """``capex / A + opex``, with every part in the result."""
    factor = (1 - 1.05**-20) / 0.05
    result = gm.evaluate.annualised_cost(heating_plant(), PRICES, day(), 0.05, 20)
    assert result.value == pytest.approx(1000.0 / factor + OPEX, rel=1e-12)
    assert result.unit == "currency/yr"
    assert to_plain(result.parts["capex"]) == {"value": 1000.0, "unit": "currency"}
    assert result.parts["opex"].value == pytest.approx(OPEX, rel=1e-12)
    assert to_plain(result.parts["annuity_factor"]) == {
        "value": pytest.approx(factor),
        "unit": "yr",
    }
    assert to_plain(result.parts["discount_rate"]) == {"value": 0.05, "unit": "-"}
    assert to_plain(result.parts["lifetime_years"]) == {"value": 20, "unit": "yr"}


def test_lcts_without_energy_has_no_value():
    """No heat and no cold: a reason, as ``lcoh`` gives; raised by default."""
    idle = day(heat=0.0)
    recorded = gm.evaluate.lcts(heating_plant(), PRICES, idle, 0.05, 20, on_error="record")
    assert recorded.value is None and "neither heat nor cold" in recorded.reason
    assert recorded.unit == "currency/J"
    with raises(gm.errors.ValidationError, "no_value", match="neither heat nor cold"):
        gm.evaluate.lcts(heating_plant(), PRICES, idle, 0.05, 20)


@pytest.mark.parametrize("name", ["lcts", "annualised_cost"])
def test_no_declared_cost_has_no_value(name):
    """A plant without a capex: a reason, or the error."""
    function = getattr(gm.evaluate, name)
    plant = heating_plant(costed=False)
    recorded = function(plant, PRICES, day(), 0.05, 20, on_error="record")
    assert recorded.value is None and "no module declares a cost" in recorded.reason
    with raises(gm.errors.ValidationError, "no_value", match="no module declares a cost"):
        function(plant, PRICES, day(), 0.05, 20)
