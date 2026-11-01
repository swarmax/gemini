"""The discount rate and the lifetime: the arguments, else the finance of the case."""

import pytest

import gemini as gm
from gemini.evaluate._utils.discounting import discounting
from gemini.units import Quantity
from tests.fixtures.errors import raises


def case_of(**finance):
    """Return a case whose finance holds ``finance``."""
    time = gm.case.Time(start="2027-01-01", end="2027-01-03", step=Quantity(1, "d"))
    return gm.Case(time=time, assumptions=gm.case.Assumptions(finance=gm.case.Finance(**finance)))


def test_the_arguments_win_over_the_case():
    """A rate and a lifetime given are used as they are."""
    case = case_of(discount_rate=0.05, lifetime=Quantity(25, "yr"))
    assert discounting(case, 0.1, 30) == (0.1, 30)


def test_the_case_gives_what_the_arguments_leave_out():
    """The lifetime is read in years."""
    case = case_of(discount_rate=0.05, lifetime=Quantity(25, "yr"))
    assert discounting(case, None, None) == (0.05, pytest.approx(25))


def test_a_value_given_nowhere_is_a_missing_assumption():
    """The path in the case is named."""
    with raises(gm.errors.ValidationError, "missing_assumption") as caught:
        discounting(case_of(), None, 10)
    assert caught.value.path == "assumptions.finance.discount_rate"
