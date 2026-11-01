"""The module-rules report on valid, broken and shipped classes."""

import json

import gemini as gm
from gemini.modules.declarations import Output, Parameter
from gemini.modules.module import Module
from tests.fixtures.booster_module import EXAMPLE, Booster


class Unitless(Module):
    """A module with a number declared without a unit."""

    category = "pumps"

    abstract = True

    def __init__(self):
        """Declare a plain float parameter."""
        super().__init__()

        # Parameters
        self.factor = Parameter(float, default=2.0)

    def forward(self, inlets):
        """Return nothing."""

        outlets = dict()
        return outlets


class Uncategorised(Unitless):
    """A module with no category."""

    category = None


class WrongSignature(Booster):
    """A module whose forward takes an extra argument."""

    abstract = True

    def forward(self, inlets, extra):
        """Return nothing."""

        outlets = dict()
        return outlets


class Broken(Booster):
    """A module that cannot be built."""

    abstract = True

    def __init__(self):
        """Fail while declaring."""
        raise ZeroDivisionError("declared badly")


class Crashing(Booster):
    """A module whose output step fails."""

    abstract = True

    def forward(self, inlets):
        """Fail on an output."""
        self.head = 1 / 0
        return super().forward(inlets)


def verdicts(report):
    """Return ``{check name: passed}`` of a report."""
    return {item["name"]: item["passed"] for item in report["checks"]}


def test_a_valid_module_passes_every_check():
    """The report names the class, passes, and is plain JSON."""
    report = gm.modules.check(Booster, EXAMPLE)
    assert report["module"] == "Booster" and report["passed"] is True
    assert verdicts(report) == {
        "is_module": True,
        "instantiate": True,
        "category": True,
        "forward_signature": True,
        "units": True,
        "describe": True,
        "call": True,
    }
    assert all(set(item) == {"name", "passed", "message"} for item in report["checks"])
    json.dumps(report, allow_nan=False)


def test_a_call_that_needs_values_is_undecided_without_an_example():
    """Without example values the call cannot run: ``None``, and the report still passes."""
    report = gm.modules.check(Booster)
    assert verdicts(report)["call"] is None
    assert "needs example values" in report["checks"][-1]["message"]
    assert report["passed"] is True


def test_each_broken_rule_fails_its_own_check():
    """A unitless number, no category and a wrong forward signature fail one check each."""
    assert verdicts(gm.modules.check(Unitless))["units"] is False
    assert verdicts(gm.modules.check(Uncategorised))["category"] is False
    assert verdicts(gm.modules.check(WrongSignature))["forward_signature"] is False


def test_the_unit_message_names_the_declaration():
    """The failed units check says which declaration lacks a unit."""
    message = gm.modules.check(Unitless)["checks"][4]["message"]
    assert "parameters.factor" in message


def test_the_report_never_raises():
    """A class that cannot be built, a crash inside a call and a non-class give failed checks."""
    broken = gm.modules.check(Broken)
    assert broken["passed"] is False
    assert "ZeroDivisionError: declared badly" in broken["checks"][-1]["message"]
    crashing = gm.modules.check(Crashing, EXAMPLE)
    assert verdicts(crashing)["call"] is False
    for not_a_module in (int, "Booster", None, Output):
        report = gm.modules.check(not_a_module)
        assert report["passed"] is False
        assert [item["name"] for item in report["checks"]] == ["is_module"]


def test_a_shipped_module_with_example_values_passes():
    """The heat consumer meets the rules when given its parameter, boundary and inlet."""
    example = {
        "parameters": {"minimum_return_temperature": {"value": 30, "unit": "degC"}},
        "inlets": {
            "supply_in": {
                "m_dot": {"value": 2, "unit": "kg/s"},
                "T": {"value": 70, "unit": "degC"},
                "p": {"value": 3, "unit": "bar"},
            }
        },
        "controls": {"heat_demand": {"value": 100, "unit": "kW"}},
    }
    report = gm.modules.check(gm.modules.HeatingGrid, example)
    assert report["passed"] is True and verdicts(report)["call"] is True
