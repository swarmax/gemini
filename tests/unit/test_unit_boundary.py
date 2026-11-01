"""One unit format: a value with a dimension is a ``Quantity``; text and bare numbers fail."""

import ast
import re

import pytest

import gemini as gm
from gemini import units
from gemini.units import Quantity
from tests.fixtures import ROOT
from tests.fixtures.errors import raises
from tests.unit.study.conftest import shallow_case, shallow_plant

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


def _plant_dict(**params):
    return lambda: gm.Plant.from_dict(
        {"format": 2, "type": "HeatingPlant", "params": params, "bindings": {}, "param_history": {}}
    )


def _plant_input(value):
    return lambda: gm.Plant.from_dict(
        {
            "format": 2,
            "type": "HeatingPlant",
            "params": {},
            "inputs": {"peak_boiler.temperature_setpoint": value},
            "bindings": {},
            "param_history": {},
        }
    )


def _minimize(bound):
    def call():
        variables = [{"path": "", "parameter": "depth", "lower": bound, "upper": 3e3}]
        return gm.study.minimize(shallow_plant(), shallow_case(), "lcts", variables)

    return call


RAW_NUMBERS = {
    "price": lambda: gm.case.Opex(electricity=2e-8),
    "co2 price": lambda: gm.case.Opex(co2=80.0),
    "cost factor": lambda: gm.case.Capex(boiler=0.5),
    "emission factor": lambda: gm.case.Emissions(CO2=gm.case.CO2(electricity=1e-7)),
    "constraint bound": lambda: gm.case.Constraint(
        on="doublet", quantity="production_flow", max=3.0
    ),
    "plant parameter": _plant_dict(depth=2500.0),
    "plant input": _plant_input(373.15),
    "study bound": _minimize(2e5),
}
"""Public inputs with a dimension, each called with a bare number."""

TEXTS = {
    "price": lambda: gm.case.Opex(electricity="100 EUR/MWh"),
    "cost factor": lambda: gm.case.Capex(boiler="0.5 EUR/W"),
    "constraint bound": lambda: gm.case.Constraint(
        on="doublet", quantity="production_flow", max="3 m3/s"
    ),
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
    with raises(gm.errors.ValidationError, "invalid_unit", match="EUR/W"):
        gm.case.Capex(boiler=Quantity(5, "EUR"))


def test_a_dimensionless_value_stays_a_number():
    """An efficiency, a fraction or a rate needs no unit."""
    values = gm.case.Finance(discount_rate=0.05)
    assert values.discount_rate == 0.05
    bound = gm.case.Constraint(on="doublet", quantity="pump_efficiency", min=0.6)
    assert bound.min == 0.6
