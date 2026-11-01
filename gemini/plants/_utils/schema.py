"""The JSON Schema of the plant dict, the input schema of a tool that builds plants."""

from gemini._utils import registry
from gemini.plants._utils.factory import GROUPS

SECTION = {"type": "object", "additionalProperties": {"type": "object"}}
BINDINGS = {
    "type": "object",
    "description": (
        "Flat bindings of one module: a control, boundary, measured output or state name, or "
        "port.field of an inlet, to a column name or {column, unit}."
    ),
    "additionalProperties": {
        "anyOf": [
            {"type": "string"},
            {
                "type": "object",
                "required": ["column", "unit"],
                "additionalProperties": False,
                "properties": {"column": {"type": "string"}, "unit": {"type": "string"}},
            },
        ]
    },
}
INPUTS = {
    "type": "object",
    "description": (
        "Inputs by path: a control or boundary such as heat_pump.temperature_setpoint, or a plant "
        "inlet field such as heating_return.T, to a number in SI or a quantity {value, unit}."
    ),
    "additionalProperties": {"anyOf": [{"type": "number"}, {"type": "object"}]},
}
PATH = {"type": "string", "pattern": r"^[^.\s]+(\.[^.\s]+)*$"}
SIZE = {
    "type": "object",
    "description": 'The structural arguments of a plant class, such as {"consumers": 3}.',
}
PORT = {"type": "string", "pattern": r"^[^.\s]+(\.[^.\s]+)+$"}


def _module():
    return {
        "type": "object",
        "required": ["type"],
        "additionalProperties": False,
        "properties": {
            "type": {"type": "string", "enum": registry.names() + sorted(GROUPS)},
            "size": SIZE,
            "params": {"type": "object"},
            "modules": {"type": "object", "additionalProperties": {"$ref": "#/$defs/module"}},
        },
    }


def _connection():
    return {
        "type": "object",
        "required": ["source", "target"],
        "additionalProperties": False,
        "properties": {
            "source": PORT,
            "target": PORT,
            "type": {"enum": ["state", None]},
        },
    }


def _output():
    two = {"type": "array", "items": PATH, "minItems": 2, "maxItems": 2}
    return {
        "type": "object",
        "minProperties": 1,
        "maxProperties": 1,
        "additionalProperties": False,
        "properties": {
            "difference": two,
            "ratio": two,
            "sum": {"type": "array", "items": PATH, "minItems": 2},
        },
    }


def _constraint():
    return {
        "type": "object",
        "required": ["target", "by", "bounds"],
        "additionalProperties": False,
        "properties": {
            "target": PATH,
            "equals": PATH,
            "at_least": PATH,
            "by": PATH,
            "bounds": {
                "anyOf": [
                    PATH,
                    {
                        "type": "array",
                        "items": {"anyOf": [PATH, {"type": "number"}]},
                        "minItems": 2,
                        "maxItems": 2,
                    },
                ]
            },
        },
    }


def _sections():
    return {
        "fluids": SECTION,
        "boundary": SECTION,
        "bindings": {"type": "object", "additionalProperties": {"$ref": "#/$defs/bindings"}},
        "param_history": {
            "type": "object",
            "additionalProperties": {"type": "array", "items": {"type": "object"}},
        },
        "inputs": INPUTS,
    }


def _of_class():
    """Return the schema of a plant of a class: which one, its size and its values."""
    return {
        "type": "object",
        "required": ["format", "type"],
        "additionalProperties": False,
        "properties": {
            "format": {"const": 2},
            "type": {"type": "string", "enum": registry.names("plants")},
            "size": SIZE,
            "params": {"type": "object"},
            **_sections(),
        },
    }


def _with_structure():
    """Return the schema of a plant that states its modules and connections."""
    ports = {
        "type": "object",
        "additionalProperties": {"anyOf": [PORT, {"type": "array", "items": PORT}]},
    }
    return {
        "type": "object",
        "required": ["format", "name", "modules", "connections"],
        "additionalProperties": False,
        "properties": {
            "format": {"const": 2},
            "name": {"type": "string"},
            "modules": {"type": "object", "additionalProperties": {"$ref": "#/$defs/module"}},
            "connections": {"type": "array", "items": _connection()},
            "inlets": ports,
            "outlets": ports,
            "outputs": {"type": "object", "additionalProperties": _output()},
            "constraints": {"type": "array", "items": _constraint()},
            **_sections(),
        },
    }


def schema():
    """Return the JSON Schema (draft 2020-12) of a plant dict, generated from the code."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "GEMINI plant dict",
        "anyOf": [_of_class(), _with_structure()],
        "$defs": {"module": _module(), "bindings": BINDINGS},
    }
