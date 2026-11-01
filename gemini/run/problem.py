"""One problem: the demand, the site, the constraints and the assumptions of a plant's run."""

import json
from collections.abc import Mapping
from copy import deepcopy
from fnmatch import fnmatchcase
from pathlib import Path

import numpy as np

from gemini import units
from gemini._utils.strings import join_path
from gemini.case._utils import demand as demand_frame
from gemini.errors import ValidationError
from gemini.run.assumptions import CARRIERS, Assumptions
from gemini.run.constraint import Constraint


class Problem:
    """What a plant is asked to do, in one object: every call takes ``(plant, problem)``.

    Parameters
    ----------
    demand : DataFrame
        The run input of ``gm.data.from_csv`` or ``from_values``, or several joined: any constant
        step and length.
    site : dict, optional
        Values of the plant parameters that describe the site, keyed by parameter path with ``*``:
        a ``Quantity`` or its dict, a plain number only for a parameter without a dimension.
        ``{"d*.gradient": Quantity(30, "K/km"), "d*.surface_temperature": Quantity(12, "degC")}``.
    constraints : list of Constraint, optional
        The limits of the run.
    assumptions : Assumptions, optional
        Rates, prices and cost factors.

    Raises
    ------
    ValidationError
        ``invalid_value`` for an argument of another type, a site value that is a text or a number
        for a parameter with a dimension, or a price profile that is not on the demand index,
        ``invalid_unit`` for a site value with an unknown unit, and what
        ``gm.data.from_csv`` raises for a demand.

    A problem lives in a folder as ``problem.json`` and a CSV of the demand next to it
    (``from_json``, ``to_json``)::

        {
          "demand": {"file": "demand.csv", "columns": {"<file column>": "heating_demand"},
                     "unit": "MW", "time_column": "date"},
          "site": {"d*.gradient": {"value": 30, "unit": "K/km"}},
          "constraints": [{"path": "d*.brine_cooling", "max": {"value": 40, "unit": "K"}}],
          "assumptions": {"prices": {"electricity": {"value": 100, "unit": "EUR/MWh"}}}
        }

    ``demand`` holds the arguments of ``gm.data.from_csv`` around a file name; ``time_column`` is
    optional, and ``site``, ``constraints`` and ``assumptions`` are the keys of ``to_dict``.
    """

    def __init__(self, demand, site=None, constraints=None, assumptions=None):
        """Validate the four parts; a part left out is empty."""
        self.demand = demand_frame.from_frame(demand)
        self.site = _checked_site({} if site is None else site)
        self.constraints = _checked_constraints([] if constraints is None else constraints)
        self.assumptions = Assumptions() if assumptions is None else assumptions
        if not isinstance(self.assumptions, Assumptions):
            raise ValidationError(
                f"problem: assumptions = {type(assumptions).__name__}; expected a gm.Assumptions",
                path="assumptions",
                code="invalid_value",
            )
        _check_price_profiles(self.assumptions, len(self.demand))

    def apply_site(self, plant):
        """Return a copy of ``plant`` with the site values, or ``plant`` when there are none.

        ``plant`` itself never changes. A pattern that matches no parameter raises ``unknown_name``
        and a parameter the plant states too raises ``conflicting_value`` naming the path.
        """
        if not self.site:
            return plant
        values = _site_values(plant, self.site)
        sited = deepcopy(plant)
        for path, params in sorted(values.items(), key=lambda item: item[0].count(".")):
            sited.set_params(path, params)
        return sited

    def to_dict(self):
        """Return the problem as plain data, the demand in the shape ``from_values`` takes."""
        return {
            "demand": demand_frame.to_dict(self.demand),
            "site": {
                path: value.to_dict() if isinstance(value, units.Quantity) else value
                for path, value in self.site.items()
            },
            "constraints": [constraint.to_dict() for constraint in self.constraints],
            "assumptions": self.assumptions.to_dict(),
        }

    @classmethod
    def from_dict(cls, data):
        """Return the problem of a dictionary of ``to_dict``."""
        _checked_keys(data)
        return cls._with_demand(demand_frame.from_dict(data["demand"]), data)

    @classmethod
    def _with_demand(cls, demand, data):
        """Return the problem of ``demand`` and the other keys of ``data``."""
        return cls(
            demand,
            data.get("site"),
            [Constraint.from_dict(item) for item in data.get("constraints", [])],
            Assumptions.from_dict(data.get("assumptions", {})),
        )

    @classmethod
    def from_json(cls, path):
        """Return the problem of a ``problem.json``, its demand read from the CSV next to it.

        Raises
        ------
        ValidationError
            ``invalid_format`` for a file that is missing or no JSON object, or a demand file that
            is missing; ``missing_value`` for a missing key (``demand``, ``demand.file``,
            ``demand.columns``, ``demand.unit``); ``unknown_name`` for an unknown key; and what
            ``gm.data.from_csv`` raises for the demand.
        """
        path = Path(path)
        data = _from_json(path)
        _checked_keys(data)
        spec = data["demand"]
        for key in ("file", "columns", "unit"):
            if not isinstance(spec, dict) or key not in spec:
                raise ValidationError(
                    f"problem {path}: demand.{key} is missing; expected file, columns and unit",
                    path=f"demand.{key}",
                    code="missing_value",
                )
        file = path.parent / spec["file"]
        if not file.is_file():
            raise ValidationError(
                f"problem {path}: demand file {str(file)!r} not found",
                path="demand.file",
                code="invalid_format",
            )
        frame = demand_frame.from_csv(file, spec["columns"], spec["unit"], spec.get("time_column"))
        return cls._with_demand(frame, data)

    def to_json(self, path):
        """Write ``path`` and the demand next to it, so that ``from_json`` gives the same problem.

        The demand goes to ``demand.csv`` when the file is named ``problem.json``, else to
        ``<stem>_demand.csv``, in W with the time column ``time``.
        """
        path = Path(path)
        name = "demand.csv" if path.stem == "problem" else f"{path.stem}_demand.csv"
        self.demand.to_csv(path.parent / name, index_label="time")
        data = self.to_dict()
        data["demand"] = {
            "file": name,
            "columns": {column: column for column in self.demand},
            "unit": "W",
            "time_column": "time",
        }
        path.write_text(json.dumps(data, indent=2) + "\n")

    @classmethod
    def schema(cls):
        """Return the JSON Schema (draft 2020-12) of ``to_dict``."""
        quantity = {
            "type": "object",
            "required": ["value", "unit"],
            "additionalProperties": False,
            "properties": {"value": {"type": "number"}, "unit": {"enum": units.names()}},
        }
        demand = {
            "type": "object",
            "required": ["start", "step", "units", "values"],
            "properties": {
                "start": {"type": "string"},
                "step": {"type": ["number", "string"]},
                "units": {"type": "object"},
                "quantities": {"type": "object"},
                "values": {
                    "type": "object",
                    "additionalProperties": {"type": "array", "items": {"type": "number"}},
                },
            },
        }
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "Problem",
            "type": "object",
            "required": ["demand"],
            "additionalProperties": False,
            "properties": {
                "demand": demand,
                "site": {
                    "type": "object",
                    "additionalProperties": {"anyOf": [{"type": "number"}, quantity]},
                },
                "constraints": {"type": "array", "items": Constraint.schema()},
                "assumptions": Assumptions.schema(),
            },
        }


def _from_json(path):
    """Return the JSON object of ``path``, or raise ``invalid_format``."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ValidationError(
            f"problem: {str(path)!r} is not a readable JSON file ({error})",
            path=str(path),
            code="invalid_format",
        ) from error
    if not isinstance(data, dict):
        raise ValidationError(
            f"problem: {str(path)!r} holds a {type(data).__name__}; expected a JSON object",
            path=str(path),
            code="invalid_format",
        )
    return data


def _checked_keys(data):
    """Raise unless ``data`` has ``demand`` and no key beyond those of ``Problem.schema``."""
    unknown = [name for name in data if name not in Problem.schema()["properties"]]
    if "demand" not in data or unknown:
        raise ValidationError(
            f"problem: keys = {sorted(data)}; expected demand, site, constraints, assumptions",
            path="demand" if "demand" not in data else unknown[0],
            code="missing_value" if "demand" not in data else "unknown_name",
        )


def _checked_site(site):
    """Return ``site``, its keys parameter paths and its values numbers or quantities."""
    if not isinstance(site, dict):
        raise ValidationError(
            f"problem: site = {type(site).__name__}; expected a dict of path to value",
            path="site",
            code="invalid_value",
        )
    checked = {}
    for path, value in site.items():
        if isinstance(value, Mapping):
            value = units.Quantity.from_dict(value)
        if not isinstance(value, (int, float, units.Quantity)) or isinstance(value, bool):
            raise ValidationError(
                f"problem: site[{path!r}] = {value!r}; expected {units.QUANTITY_FORM}, or a "
                "number for a parameter without a dimension",
                path=f"site.{path}",
                code="invalid_value",
            )
        checked[path] = value
    return checked


def _matching_modules(plant, pattern):
    """Return the paths of the modules of ``plant`` that fit ``pattern``, name by name."""
    wanted = pattern.split(".")
    return [
        path
        for path, _ in plant.named_modules()
        if len(path.split(".")) == len(wanted) and all(map(fnmatchcase, path.split("."), wanted))
    ]


def _site_values(plant, site):
    """Return ``{module path: {parameter: value}}`` of ``site``, each match checked on its own."""
    values = {}
    for pattern, value in site.items():
        modules, _, name = pattern.rpartition(".")
        found = [
            path
            for path in _matching_modules(plant, modules)
            if name in plant.get_submodule(path)._parameters
        ]
        if not found:
            raise ValidationError(
                f"problem: site path {pattern!r} matches no parameter",
                path=f"site.{pattern}",
                code="unknown_name",
            )
        for path in found:
            if plant.get_submodule(path)._params_at(None).get(name) is not None:
                raise ValidationError(
                    f"problem: site path {pattern!r} sets {join_path(path, name)}, which the "
                    "plant states too; expected one of the two",
                    path=join_path(path, name),
                    code="conflicting_value",
                )
            _checked_dimension(plant.get_submodule(path), name, value, pattern)
            values.setdefault(path, {})[name] = value
    return values


def _checked_dimension(module, name, value, pattern):
    """Raise unless a parameter with a dimension gets a quantity, not a plain number."""
    unit = module._parameters[name].unit
    if unit not in (None, "-") and not isinstance(value, units.Quantity):
        raise ValidationError(
            f"problem: site[{pattern!r}] = {value!r}; expected {units.QUANTITY_FORM}, because "
            f"{name} has the unit {unit!r}",
            path=f"site.{pattern}",
            code="invalid_value",
        )


def _checked_constraints(constraints):
    """Return ``constraints`` as a list, or raise for an item that is no ``Constraint``."""
    for constraint in constraints:
        if not isinstance(constraint, Constraint):
            raise ValidationError(
                f"problem: constraint = {constraint!r}; expected a gm.Constraint",
                path="constraints",
                code="invalid_value",
            )
    return list(constraints)


def _check_price_profiles(assumptions, rows):
    """Raise unless every price profile has one value per row of the demand."""
    for carrier in CARRIERS:
        price = assumptions.price(carrier, required=False)
        if isinstance(price, np.ndarray) and len(price) != rows:
            raise ValidationError(
                f"problem: price of {carrier} has {len(price)} values; expected {rows}, one per "
                "row of the demand",
                path=f"assumptions.prices.{carrier}",
                code="invalid_value",
            )
