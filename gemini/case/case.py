"""The case: everything a plant is asked to do and everything around it, in one object."""

import json
from pathlib import Path

import numpy as np
from pydantic import model_validator

from gemini._utils.strings import join_path
from gemini.case._utils import profile
from gemini.case._utils.section import Section
from gemini.case.assumptions import Assumptions
from gemini.case.choices import Choices
from gemini.case.constraint import Constraint
from gemini.case.demand import NAMES, Demand
from gemini.case.environment import Environment
from gemini.case.time import Time
from gemini.errors import ValidationError


class Case(Section):
    """What a plant is asked to do, in fixed sections, for every call: ``(plant, case)``.

    Sections, in this order: ``time``, ``environment``, ``demand``, ``choices``, ``constraints``
    and ``assumptions``. Everything is stored in SI as plain numbers or arrays; ``to_dict`` and
    ``to_json`` write ``{"value", "unit"}`` in the SI unit. Nothing has a default: a value that is
    absent is ``None``, and a call that needs it raises ``missing_value`` (``missing_assumption``
    below ``assumptions``) naming its path. Every profile (the demand, the air, a price, the CO2
    intensity) lies on ``time.index``.

    ``from_json`` reads a ``case.json`` and the CSV files named in it from the same folder;
    ``to_json`` writes them back, so that ``Case.from_json(path) == case``.

    Attributes
    ----------
    time : Time
    environment : Environment or None
    demand : Demand or None
    choices : Choices or None
    constraints : tuple of Constraint or None
    assumptions : Assumptions or None
    """

    where = ""
    time: Time
    environment: Environment | None = None
    demand: Demand | None = None
    choices: Choices | None = None
    constraints: tuple[Constraint, ...] | None = None
    assumptions: Assumptions | None = None

    @model_validator(mode="after")
    def _on_the_time(self):
        """Refuse a demand or a profile that is not on the steps of ``time``."""
        index = self.time.index
        if self.demand is not None:
            profile.check_index(self.demand.frame.index, index, self.demand.file, "demand.file")
        for path, values in _arrays(self):
            if len(values) != len(index):
                raise ValidationError(
                    f"{path}: profile has {len(values)} values; expected {len(index)}, the "
                    "steps of time",
                    path=path,
                    code="invalid_value",
                )
        return self

    @classmethod
    def from_dict(cls, data, folder=None):
        """Return the case of a dictionary of ``to_dict``.

        ``folder`` is where the demand file and the profile files named in ``data`` are read.
        Without it they are read from the working folder.
        """
        if not isinstance(data, dict):
            return super().from_dict(data)
        data = dict(data)
        if isinstance(data.get("demand"), dict) and "file" in data["demand"]:
            file = Path(folder or ".") / data["demand"]["file"]
            data["demand"] = {**data["demand"], "file": str(file)}
        return cls(**_with_profiles(data, folder))

    @classmethod
    def from_json(cls, path):
        """Return the case of a ``case.json``, its CSV files read from the same folder.

        Raises
        ------
        ValidationError
            ``invalid_format`` for a file that is missing or no JSON object, a file named in it
            that is missing; and what the sections raise for a value they refuse.
        """
        path = Path(path)
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError) as error:
            raise ValidationError(
                f"case: {str(path)!r} is not a readable JSON file ({error})",
                path=str(path),
                code="invalid_format",
            ) from error
        if not isinstance(data, dict):
            raise ValidationError(
                f"case: {str(path)!r} holds a {type(data).__name__}; expected a JSON object",
                path=str(path),
                code="invalid_format",
            )
        return cls.from_dict(data, path.parent)

    def to_json(self, path):
        """Write ``path`` and, next to it, the CSV files of the demand and of every profile."""
        path = Path(path)
        data = _written(self.to_dict(), "", self.time.index, path.parent / path.stem)
        if self.demand is not None:
            _demand_to_csv(self.demand, path.parent)
        path.write_text(json.dumps(data, indent=2) + "\n")


def _arrays(section, prefix=""):
    """Yield ``(path, array)`` of every profile below ``section``."""
    for name in type(section).model_fields:
        value, path = getattr(section, name), join_path(prefix, name)
        if isinstance(value, np.ndarray):
            yield path, value
        elif isinstance(value, Section):
            yield from _arrays(value, path)
        elif isinstance(value, tuple):
            for number, item in enumerate(value):
                yield from _arrays(item, f"{path}[{number}]")


def _with_profiles(data, folder):
    """Return ``data`` with every ``{"file", "column", "unit"}`` profile read from its CSV."""
    if "time" not in data or not any(
        isinstance(data.get(name), dict) for name in ("environment", "assumptions")
    ):
        return data
    index = Time.from_dict(data.get("time")).index
    for name in ("environment", "assumptions"):
        if isinstance(data.get(name), dict):
            data[name] = _resolved(data[name], name, folder, index)
    return data


def _resolved(node, path, folder, index):
    """Return ``node`` with its profiles read."""
    if profile.is_profile(node):
        return profile.from_csv(node, folder, index, path)
    if isinstance(node, dict):
        return {
            key: _resolved(item, join_path(path, key), folder, index) for key, item in node.items()
        }
    return node


def _written(node, path, index, stem):
    """Return ``node`` with every profile written to a CSV next to the JSON and named."""
    if (
        isinstance(node, dict)
        and set(node) == {"value", "unit"}
        and isinstance(node["value"], list)
    ):
        name = path.replace(".", "_")
        file = stem.with_name(f"{stem.name}_{name}.csv")
        profile.to_csv(node["value"], index, path.rsplit(".", 1)[-1], file)
        return {"file": file.name, "column": path.rsplit(".", 1)[-1], "unit": node["unit"]}
    if isinstance(node, dict):
        return {
            key: _written(item, join_path(path, key), index, stem) for key, item in node.items()
        }
    if isinstance(node, list):
        return [
            _written(item, f"{path}[{number}]", index, stem) for number, item in enumerate(node)
        ]
    return node


def _demand_to_csv(demand, folder):
    """Write the demand frame as the CSV ``demand.file``, in W under the columns of the services."""
    columns = {NAMES[name]: getattr(demand, name).column for name in NAMES if getattr(demand, name)}
    frame = demand.frame.rename(columns=columns)
    frame.to_csv(folder / demand.file, index_label=demand.time_column or "time")
