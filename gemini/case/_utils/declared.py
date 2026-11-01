"""Reading and writing the ``uncertainty`` that a value of the case carries next to it.

In ``case.json`` a number of ``environment`` or ``assumptions`` may be
``{"value", "unit", "uncertainty": {...}}`` (a dimensionless one ``{"value", "uncertainty"}``).
``extract`` takes the declarations out of the dict before the sections are built, ``resolve``
checks them against the built case and stores them in SI, and ``attach`` puts them back into
``to_dict``.
"""

import copy

from gemini import units
from gemini._utils.strings import close_matches, join_names
from gemini.case._utils.fields import Q, QMap, is_number, si_unit_of, to_si
from gemini.case._utils.section import object_schema
from gemini.case.uncertainty import KINDS, Uncertainty
from gemini.errors import ValidationError

KEY = "uncertainty"
CARRIERS = ("environment", "assumptions")
"""The sections whose numbers may carry an uncertainty."""
_REQUIRED = {"uniform": ("min", "max"), "triangular": ("min", "max"), "normal": ("std",)}
_OPTIONAL = {"uniform": (), "triangular": (), "normal": ("min", "max")}


def _error(path, message, code):
    """Return the error of a declaration at ``path``."""
    return ValidationError(f"{path}: {message}", path=path, code=code)


def _walk(node, path):
    """Yield ``(path, key)`` of every dict below ``node`` that holds an uncertainty."""
    if isinstance(node, dict):
        if KEY in node:
            yield path
        for key, item in node.items():
            if key != KEY:
                yield from _walk(item, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for number, item in enumerate(node):
            yield from _walk(item, f"{path}[{number}]")


def refuse_elsewhere(data):
    """Raise ``invalid_value`` for an uncertainty below a section that may not carry one."""
    for name, node in data.items():
        if name not in CARRIERS:
            for path in _walk(node, name):
                raise _error(
                    f"{path}.{KEY}",
                    f"{name} cannot carry an uncertainty; only {join_names(CARRIERS)} can",
                    "invalid_value",
                )


def extract(data):
    """Return ``(data, found)``: ``data`` without them, ``found`` as ``{path: (raw, unit)}``.

    A node that carries one becomes its plain number when it has no unit. A node that holds
    anything but a number (a profile, a file) raises ``invalid_value``.
    """
    refuse_elsewhere(data)
    data, found = copy.deepcopy(data), {}
    for name in CARRIERS:
        if isinstance(data.get(name), dict):
            data[name] = _strip(data[name], name, found)
    return data, found


def _strip(node, path, found):
    """Return ``node`` without declarations, recording each in ``found``."""
    if not isinstance(node, dict):
        return node
    if KEY in node and "value" in node:
        rest = {key: item for key, item in node.items() if key != KEY}
        if set(rest) - {"value", "unit"} or not is_number(rest["value"]):
            raise _error(
                f"{path}.{KEY}",
                "only a number with its unit can carry an uncertainty, not a profile",
                "invalid_value",
            )
        found[path] = (node[KEY], rest.get("unit"))
        return rest if "unit" in rest else rest["value"]
    return {
        key: _strip(item, f"{path}.{key}", found) if key != KEY else item
        for key, item in node.items()
    }


def _meta_and_value(case, path):
    """Return ``(meta, value)``: the quantity of the field at ``path`` and its SI value."""
    node, meta = case, None
    for part in path.split("."):
        if isinstance(node, dict):
            node = node[part]
            continue
        field = type(node).model_fields[part]
        meta = next((m for m in field.metadata if isinstance(m, (Q, QMap))), None)
        node = getattr(node, part)
    return meta, node


def _si(path, key, number, unit, quantity, difference):
    """Return ``number``, given in ``unit``, in SI; a ``difference`` ignores a unit offset."""
    if not is_number(number):
        raise _error(f"{path}.{KEY}.{key}", f"{number!r}; expected a number", "invalid_value")
    if unit is None:
        return float(number)
    try:
        converted = to_si(units.Quantity(number, unit), quantity)
        return converted - to_si(units.Quantity(0.0, unit), quantity) if difference else converted
    except ValidationError as error:
        raise _error(f"{path}.{KEY}.{key}", str(error), error.code) from error


def _keys(path, raw):
    """Return the kind of ``raw`` after checking its keys against that kind."""
    if not isinstance(raw, dict):
        raise _error(f"{path}.{KEY}", f"{raw!r}; expected a dict with a kind", "invalid_value")
    if "kind" not in raw:
        raise _error(
            f"{path}.{KEY}.kind", f"is missing; expected {join_names(KINDS)}", "missing_value"
        )
    kind = raw["kind"]
    if kind not in KINDS:
        raise ValidationError(
            f"{path}.{KEY}.kind: {kind!r}; expected one of {join_names(KINDS)}",
            path=f"{path}.{KEY}.kind",
            code="unknown_name",
            suggestions=close_matches(str(kind), list(KINDS)),
        )
    allowed = ("kind", *_REQUIRED[kind], *_OPTIONAL[kind])
    for key in raw:
        if key not in allowed:
            raise _error(
                f"{path}.{KEY}.{key}",
                f"unknown key for {kind}; expected one of {join_names(allowed)}",
                "unknown_name",
            )
    for key in _REQUIRED[kind]:
        if key not in raw:
            raise _error(f"{path}.{KEY}.{key}", f"is missing; {kind} needs it", "missing_value")
    return kind


def _checked(path, numbers, value, meta):
    """Raise unless the value lies inside ``min`` and ``max`` and both respect the field bounds."""
    low, high = numbers.get("min"), numbers.get("max")
    if low is not None and value < low:
        raise _error(
            f"{path}.{KEY}.min", "is above the value; expected min <= value", "out_of_bounds"
        )
    if high is not None and value > high:
        raise _error(
            f"{path}.{KEY}.max", "is below the value; expected value <= max", "out_of_bounds"
        )
    if not isinstance(meta, Q):
        return
    for key in ("min", "max"):
        if key in numbers:
            try:
                meta.convert(units.Quantity(numbers[key], si_unit_of(meta.quantity)))
            except ValidationError as error:
                raise _error(f"{path}.{KEY}.{key}", str(error), error.code) from error


def _parsed(path, raw, unit, meta, value):
    """Return the ``Uncertainty`` of one declaration, in SI, checked against the value."""
    kind = _keys(path, raw)
    numbers = {
        key: _si(path, key, raw[key], unit, meta.quantity, key == "std")
        for key in raw
        if key != "kind"
    }
    if "std" in numbers and numbers["std"] <= 0:
        raise _error(f"{path}.{KEY}.std", "expected more than 0", "out_of_bounds")
    _checked(path, numbers, value, meta)
    return Uncertainty(kind=kind, **numbers)


def resolve(case, found):
    """Return ``{path: Uncertainty}`` of the declarations ``found`` in the dict of ``case``."""
    result = {}
    for path, (raw, unit) in found.items():
        meta, value = _meta_and_value(case, path)
        if meta is None or value is None:
            raise _error(
                path, "cannot carry an uncertainty; it is no number with a unit", "invalid_value"
            )
        result[path] = _parsed(path, raw, unit, meta, value)
    return result


def attach(data, uncertainty):
    """Return ``data``, the ``to_dict`` of a case, with each uncertainty next to its value."""
    for path, item in uncertainty.items():
        *parents, last = path.split(".")
        node = data
        for part in parents:
            node = node[part]
        value = node[last]
        node[last] = (
            {**value, KEY: item.to_dict()}
            if isinstance(value, dict)
            else {"value": value, KEY: item.to_dict()}
        )
    return data


def with_schema(node):
    """Return a JSON Schema ``node`` with the optional ``uncertainty`` added to each number."""
    if isinstance(node, list):
        return [with_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    node = {key: with_schema(item) for key, item in node.items()}
    properties = node.get("properties", {})
    if node.get("required") == ["value", "unit"]:
        node["properties"] = {**properties, KEY: object_schema(Uncertainty)}
    elif "anyOf" in node and {"type": "number"} in node["anyOf"]:
        bare = {
            "type": "object",
            "additionalProperties": False,
            "required": ["value", KEY],
            "properties": {"value": {"type": "number"}, KEY: object_schema(Uncertainty)},
        }
        node["anyOf"] = [*node["anyOf"], bare]
    return node
