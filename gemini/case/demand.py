"""The demand of a case: a CSV file and the heating and cooling services read from it."""

from pathlib import Path
from typing import Annotated, Any

import pandas as pd
from pydantic import Field, field_validator, model_validator

from gemini import units
from gemini._utils.strings import join_names
from gemini.case._utils import demand as demand_frame
from gemini.case._utils.fields import Q, Shape
from gemini.case._utils.section import Section
from gemini.errors import ValidationError

NAMES = {"heating": "heating_demand", "cooling": "cooling_demand"}
"""The service names, each with the column of the demand frame it fills."""


class Service(Section):
    """A heating or cooling service: its column in the file and its temperatures.

    Attributes
    ----------
    column : str
        The file column of the demand.
    unit : Unit
        The power unit of the column; inside a ``Demand`` it is ``W``, because the demand frame
        is stored in SI.
    supply_temperature, return_temperature : float or None
        What the consumer asks to be supplied at, and the temperature it returns at [K].
    """

    where = "demand"
    column: str
    unit: Annotated[units.Unit, Shape({"enum": units.names("power")})]
    supply_temperature: Annotated[Any, Q("temperature", minimum=(0.0, True))] = None
    return_temperature: Annotated[Any, Q("temperature", minimum=(0.0, True))] = None

    @field_validator("unit", mode="before")
    @classmethod
    def _power(cls, unit):
        """Return a power unit, or raise ``invalid_unit``."""
        if not isinstance(unit, str) or not units.fits(unit, "power"):
            raise ValidationError(
                f"unit {unit!r} is not a power; expected one of {join_names(units.names('power'))}",
                code="invalid_unit",
            )
        return units.Unit(unit)


class Demand(Section):
    """The demand file and its services; at least one of ``heating`` and ``cooling``.

    The file is read when the demand is built. ``file`` keeps its name only, because
    ``Case.to_json`` writes the demand next to the JSON under that name, in W.

    Attributes
    ----------
    file : str
        Name of the CSV file.
    time_column : str or None
        The column of the timestamps; the first column when absent.
    heating, cooling : Service or None
        The services.
    frame : DataFrame
        The demand in W on a UTC ``time`` index, columns ``heating_demand`` and ``cooling_demand``
        for the services given.
    """

    where = "demand"
    file: str
    time_column: str | None = None
    heating: Service | None = None
    cooling: Service | None = None
    frame: Any = Field(default=None, json_schema_extra={"hidden": True})

    @model_validator(mode="before")
    @classmethod
    def _read(cls, data):
        """Read the file once; the services then state ``W``, in a frame of SI values."""
        if not isinstance(data, dict) or data.get("frame") is not None:
            return data
        given = {name: data[name] for name in NAMES if data.get(name) is not None}
        if not given or not isinstance(data.get("file"), str):
            return data
        specs = {name: _spec(item) for name, item in given.items()}
        if None in specs.values():
            return data
        path = Path(data["file"])
        if not path.is_file():
            raise ValidationError(
                f"demand.file: {str(path)!r} not found", path="demand.file", code="invalid_format"
            )
        frames = [
            demand_frame.from_csv(path, {column: NAMES[name]}, unit, data.get("time_column"))
            for name, (column, unit) in specs.items()
        ]
        frame = pd.concat(frames, axis=1)
        frame.attrs = {
            "units": dict.fromkeys(frame, "W"),
            "quantities": dict.fromkeys(frame, "power"),
        }
        watts = {name: _in_watts(item) for name, item in given.items()}
        return {**data, "file": path.name, "frame": frame, **watts}

    @model_validator(mode="after")
    def _served(self):
        """Refuse a demand without a service."""
        if self.heating is None and self.cooling is None:
            raise ValidationError(
                "heating and cooling are absent; expected at least one", code="missing_value"
            )
        return self


def _spec(service):
    """Return ``(column, unit)`` of a service given as a dict or a ``Service``, or ``None``."""
    column = (
        service.get("column") if isinstance(service, dict) else getattr(service, "column", None)
    )
    unit = service.get("unit") if isinstance(service, dict) else getattr(service, "unit", None)
    if not isinstance(column, str) or not isinstance(unit, str) or not units.fits(unit, "power"):
        return None
    return column, unit


def _in_watts(service):
    """Return the service with the unit ``W``: the frame it reads is in W."""
    if isinstance(service, dict):
        return {**service, "unit": "W"}
    return service.model_copy(update={"unit": units.Unit.W})
