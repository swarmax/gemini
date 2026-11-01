"""The base of every part of the case: a strict, frozen pydantic model with SI values.

A ``Section`` refuses unknown keys, stores quantities in SI, writes ``to_dict`` with
``{"value", "unit"}`` in the SI unit and reports a failure as a ``gm.errors.ValidationError`` that
names the path of the case.
"""

import types
import typing
from contextvars import ContextVar
from enum import Enum

import numpy as np
import pandas as pd
import pydantic
from pydantic import BaseModel, ConfigDict

from gemini import units
from gemini._utils.strings import close_matches, join_names
from gemini.case._utils.fields import Q, QMap, Shape, quantity_dict, quantity_schema
from gemini.errors import ValidationError

_DEPTH = ContextVar("case_depth", default=0)
"""How many sections are being built: only the outermost one reports a failure."""
_CODES = {
    "missing": "missing_value",
    "extra_forbidden": "unknown_name",
    "greater_than": "out_of_bounds",
    "greater_than_equal": "out_of_bounds",
    "less_than": "out_of_bounds",
    "less_than_equal": "out_of_bounds",
    "too_short": "out_of_bounds",
}
"""The code of what pydantic refuses itself; anything else is ``invalid_value``."""


class Section(BaseModel):
    """A part of the case. ``where`` is the path of the part in ``case.json``."""

    model_config = ConfigDict(
        extra="forbid", frozen=True, allow_inf_nan=False, arbitrary_types_allowed=True
    )
    where: typing.ClassVar[str] = ""

    def __init__(self, **data):
        """Validate the fields; the outermost section raises a ``ValidationError``."""
        token = _DEPTH.set(_DEPTH.get() + 1)
        try:
            super().__init__(**data)
        except pydantic.ValidationError as error:
            if _DEPTH.get() > 1:
                raise
            raise _failure(type(self), error) from error
        finally:
            _DEPTH.reset(token)

    @classmethod
    def from_dict(cls, data):
        """Return the part of a dictionary of ``to_dict``."""
        if not isinstance(data, dict):
            raise ValidationError(
                f"{cls.where or 'case'}: {type(data).__name__}; expected a dict",
                path=cls.where,
                code="invalid_value",
            )
        return cls(**data)

    def to_dict(self):
        """Return the part as plain data, quantities as ``{"value", "unit"}`` in SI."""
        data = {}
        for name, info in type(self).model_fields.items():
            value = getattr(self, name)
            if value is not None and not _hidden(info):
                data[name] = _plain(value, info)
        return data

    @classmethod
    def schema(cls):
        """Return the JSON Schema (draft 2020-12) of ``to_dict``."""
        head = {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": cls.__name__}
        return head | object_schema(cls)

    def __eq__(self, other):
        """Compare field by field, arrays and frames by value."""
        if type(other) is not type(self):
            return NotImplemented
        return all(same(getattr(self, n), getattr(other, n)) for n in type(self).model_fields)

    __hash__ = None


def same(left, right):
    """Whether two field values are equal, an array or a frame by its numbers."""
    if isinstance(left, (np.ndarray, pd.DataFrame)) or isinstance(
        right, (np.ndarray, pd.DataFrame)
    ):
        if isinstance(left, pd.DataFrame) and isinstance(right, pd.DataFrame):
            return bool(left.equals(right))
        return bool(np.array_equal(left, right))
    if isinstance(left, (tuple, list)) and isinstance(right, (tuple, list)):
        return len(left) == len(right) and all(same(a, b) for a, b in zip(left, right))
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(same(left[k], right[k]) for k in left)
    return bool(left == right)


def _hidden(info):
    """Whether a field is kept out of ``to_dict`` (the frame of a demand)."""
    return bool((info.json_schema_extra or {}).get("hidden"))


def _meta(info, kind):
    """Return the metadata of ``info`` that is a ``kind``, or ``None``."""
    return next((item for item in info.metadata if isinstance(item, kind)), None)


def _plain(value, info):
    """Return a field value as plain data."""
    quantity, mapped = _meta(info, Q), _meta(info, QMap)
    if quantity is not None:
        return quantity_dict(value, quantity.quantity)
    if mapped is not None:
        return {key: quantity_dict(item, mapped.quantity) for key, item in value.items()}
    return _data(value)


def _data(value):
    """Return ``value`` as plain data."""
    if isinstance(value, Section):
        return value.to_dict()
    if isinstance(value, tuple):
        return [_data(item) for item in value]
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, dict):
        return {key: _data(item) for key, item in value.items()}
    return value


def _path(parts):
    """Return the dotted path of ``parts``, an index in brackets."""
    path = ""
    for part in parts:
        path += f"[{part}]" if isinstance(part, int) else f".{part}"
    return path.lstrip(".")


def _failure(cls, error):
    """Return the ``ValidationError`` of the first problem pydantic found."""
    first = error.errors()[0]
    loc = [item for item in first["loc"] if isinstance(item, (str, int))]
    inner = first.get("ctx", {}).get("error")
    if first["type"] == "extra_forbidden":
        return _unknown(cls, loc)
    if isinstance(inner, ValidationError) and inner.path:
        return ValidationError(str(inner), path=inner.path, code=inner.code)
    if isinstance(inner, ValidationError):
        message, code = str(inner), inner.code
    elif first["type"] == "missing":
        message, code = "is missing", "missing_value"
    else:
        message, code = first["msg"], _CODES.get(first["type"], "invalid_value")
    path = _path([*_split(cls.where), *loc])
    return ValidationError(f"{path}: {message}", path=path, code=code)


def _unknown(cls, loc):
    """Return the ``unknown_name`` error for the key that ends ``loc``."""
    owner = cls
    for part in loc[:-1]:
        if owner is not None and isinstance(part, str):
            owner = _section_of(owner.model_fields[part].annotation)
    known = list(owner.model_fields) if owner is not None else []
    key = str(loc[-1])
    near = [name for name in known if key in name or name in key]
    near += [name for name in close_matches(key, known) if name not in near]
    path = _path([*_split(cls.where), *loc[:-1]])
    return ValidationError(
        f"{path or 'case'}: unknown key {key!r}; expected one of {join_names(known)}"
        f"{f'; did you mean {near[0]!r}?' if near else ''}",
        path=path,
        suggestions=near,
        code="unknown_name",
    )


def _split(where):
    """Return the parts of a dotted path."""
    return [part for part in where.split(".") if part]


def _section_of(annotation):
    """Return the ``Section`` class an annotation holds, looking through ``None`` and tuples."""
    for item in typing.get_args(annotation) or (annotation,):
        if isinstance(item, type) and issubclass(item, Section):
            return item
        if typing.get_args(item):
            found = _section_of(item)
            if found is not None:
                return found
    return None


def object_schema(cls):
    """Return the object schema of a section class, closed at every level."""
    properties = {}
    for name, info in cls.model_fields.items():
        if not _hidden(info):
            properties[name] = field_schema(info)
    required = [n for n, i in cls.model_fields.items() if i.is_required() and not _hidden(i)]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def field_schema(info):
    """Return the JSON Schema of one field."""
    quantity, mapped, shape = _meta(info, Q), _meta(info, QMap), _meta(info, Shape)
    if shape is not None:
        return dict(shape.schema)
    if quantity is not None:
        return quantity_schema(quantity.quantity, quantity.profile)
    if mapped is not None:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {key: quantity_schema(mapped.quantity) for key in mapped.keys},
        }
    return annotation_schema(info.annotation)


def annotation_schema(annotation):
    """Return the JSON Schema of a type annotation."""
    arguments = [a for a in typing.get_args(annotation) if a is not type(None)]
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        return annotation_schema(arguments[0])
    if origin is typing.Literal:
        return {"enum": list(arguments)}
    if origin is tuple:
        return {"type": "array", "items": annotation_schema(arguments[0])}
    if origin is dict:
        return {"type": "object", "additionalProperties": annotation_schema(arguments[1])}
    if isinstance(annotation, type) and issubclass(annotation, Section):
        return object_schema(annotation)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return {"enum": units.names()}
    return {"type": _TYPES.get(annotation)} if annotation in _TYPES else {}


_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}
