"""The values a study may vary: parameters of the plant and ``case.<path>`` numbers."""

import pytest

import gemini as gm
from gemini.study._utils import target
from tests.fixtures.errors import raises
from tests.unit.study.conftest import shallow_case, shallow_plant

PRICE = "case.assumptions.finance.opex.electricity"


def test_a_number_of_the_case_is_set_in_si_on_a_copy():
    """The change is in the copy only, and other values stay."""
    case = shallow_case()
    changed = target.with_case_values(
        case, {PRICE: 2e-8, "case.assumptions.finance.discount_rate": 0.1}
    )
    assert changed.assumptions.finance.opex.electricity == 2e-8
    assert changed.assumptions.finance.discount_rate == 0.1
    assert changed.assumptions.finance.opex.gas == case.assumptions.finance.opex.gas
    assert case.assumptions.finance.opex.electricity != 2e-8


def test_a_bound_of_the_field_is_kept():
    """A negative discount rate is refused."""
    with raises(gm.errors.ValidationError, "out_of_bounds"):
        target.with_case_values(shallow_case(), {"case.assumptions.finance.discount_rate": -1})


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("case.constraints", "invalid_value"),
        ("case.time.start", "invalid_value"),
        ("case.assumptions.finance.currency", "invalid_value"),
        ("case.assumptions.finance.opexx", "unknown_name"),
        ("case.assumptions.finance.revenue.heat", "missing_value"),
    ],
)
def test_a_name_that_is_no_number_of_the_case_is_refused(name, code):
    """The message names the path."""
    with raises(gm.errors.ValidationError, code, match=name):
        target.case_field(shallow_case(), name)


def test_a_bound_is_read_in_the_unit_of_its_value():
    """A plant parameter and a number of the case; a plain number only without a dimension."""
    plant, case = shallow_plant(), shallow_case()
    assert target.value_si(plant, case, "depth", gm.units.Quantity(2, "km")) == 2000
    assert target.value_si(plant, case, PRICE, {"value": 36, "unit": "EUR/MWh"}) == pytest.approx(
        1e-8
    )
    assert target.value_si(plant, case, "d0.pump_efficiency", 0.7) == 0.7
    assert target.unit_of(plant, case, PRICE) == "currency/J"
    with raises(gm.errors.ValidationError, "invalid_value"):
        target.value_si(plant, case, "depth", 2000)
    with raises(gm.errors.ValidationError, "invalid_value"):
        target.value_si(plant, case, PRICE, 3.0)


def test_a_spread_ignores_the_offset_of_a_unit():
    """A standard deviation of 2 degC is 2 K."""
    case = shallow_case()
    name = "case.environment.air.temperature"
    spread = target.value_si(
        shallow_plant(), case, name, gm.units.Quantity(2, "degC"), difference=True
    )
    assert spread == pytest.approx(2.0)
