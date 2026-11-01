"""One unit format: a value with a dimension is a ``Quantity``; text and bare numbers fail."""

import ast
import re

import pytest

import gemini as gm
from gemini import units
from gemini.units import Quantity
from tests.fixtures import ROOT
from tests.fixtures.costed_plants import heating_plant
from tests.fixtures.errors import raises
from tests.fixtures.result_tables import make_problem, make_results

TEXT = re.compile(r"\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\s+(\S+)\s*")
QUOTED = re.compile(r"[\"'][+-]?[.\d][^\"'\n]* \S+[\"']")


def _documented(tree):
    """Return the docstring nodes of a module."""
    scopes = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    return {
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(node, scopes) and ast.get_docstring(node, clean=False) is not None
    }


def _unit_texts(path):
    """Return the strings of a source file that are a number followed by a unit."""
    source = path.read_text()
    if not QUOTED.search(source):
        return []
    tree = ast.parse(source)
    docstrings = _documented(tree)
    strings = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    matches = [(node, TEXT.fullmatch(node.value)) for node in strings if node not in docstrings]
    return [
        f"{path.relative_to(ROOT)}:{node.lineno}: {node.value!r}"
        for node, match in matches
        if match and units.si_unit(match.group(1)) is not None
    ]


def test_no_package_code_reads_or_holds_unit_text():
    """No string of the package is a number followed by a unit: nothing parses unit text."""
    found = [text for path in sorted((ROOT / "gemini").rglob("*.py")) for text in _unit_texts(path)]
    assert found == []


def _assumptions(**fields):
    return lambda: gm.Assumptions(**fields)


def _site(value):
    def call():
        problem = make_problem(site={"heat.return_temperature": value})
        return problem.apply_site(heating_plant())

    return call


def _constraint(**bounds):
    def call():
        problem = make_problem(count=4, constraints=[gm.Constraint("heat.unmet_demand", **bounds)])
        results = make_results({"heat": {"unmet_demand": [1.0, 2.0, 3.0, 4.0]}})
        return gm.evaluate.constraints(heating_plant(), problem, results)

    return call


def _minimize(bound):
    def call():
        variables = [{"path": "boiler", "parameter": "capacity", "lower": bound, "upper": 3e6}]
        plant = gm.Plant("Boiler")
        plant.add("Boiler", name="boiler")
        return gm.study.minimize(plant, None, variables, "peak_heat", plan=None)

    return call


RAW_NUMBERS = {
    "price": _assumptions(prices={"electricity": 2e-8}),
    "co2 price": _assumptions(co2_price=80.0),
    "cost factor": _assumptions(pump_cost=0.5),
    "emission factor": _assumptions(electricity_emission_factor=1e-7),
    "site": _site(300.0),
    "constraint bound": _constraint(max=3.0),
    "study bound": _minimize(2e5),
}
"""Public inputs with a dimension, each called with a bare number."""

TEXTS = {
    "price": _assumptions(prices={"electricity": "100 EUR/MWh"}),
    "cost factor": _assumptions(pump_cost="0.5 EUR/W"),
    "site": _site("300 K"),
    "constraint bound": lambda: gm.Constraint("heat.unmet_demand", max="3 W"),
    "set_params": lambda: gm.modules.Pipe().set_params("", {"length": "10 m"}),
    "stream": lambda: gm.Stream(flow="150 m3/h", T=300, p=1e5),
    "fluid": lambda: gm.Fluid(density="1000 kg/m3"),
    "call": lambda: gm.call("Pipe", {"length": "10 m"}, {}, {}),
}
"""Public inputs called with unit text."""


@pytest.mark.parametrize("name", RAW_NUMBERS)
def test_a_bare_number_with_a_dimension_is_refused(name):
    """A price, a cost, a site value or a bound without its unit raises ``invalid_value``."""
    with raises(gm.errors.ValidationError, "invalid_value"):
        RAW_NUMBERS[name]()


@pytest.mark.parametrize("name", TEXTS)
def test_unit_text_is_refused_everywhere(name):
    """Text such as ``"2500 m"`` is no value: the message shows the dict form."""
    with raises(gm.errors.ValidationError, "invalid_value", match="'value'"):
        TEXTS[name]()


def test_a_quantity_of_another_dimension_is_refused_naming_the_field():
    """A length where a flow is wanted lists the units of a flow."""
    with raises(gm.errors.ValidationError, "invalid_unit", match="m3/h"):
        gm.modules.Pipe().set_params("", {"length": Quantity(5, "m3/h")})
    with raises(gm.errors.ValidationError, "invalid_unit", match="currency/W"):
        gm.Assumptions(pump_cost=Quantity(5, "EUR"))


def test_a_dimensionless_value_stays_a_number():
    """An efficiency, a fraction or a rate needs no unit."""
    values = gm.Assumptions(discount_rate=0.05, heat_cost_share=0.8)
    assert values.discount_rate == 0.05
    assert gm.Constraint("heat.efficiency", min=0.6).min == 0.6
