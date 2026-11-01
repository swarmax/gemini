"""The time of a case: the first instant, the end that is excluded, and the step."""

from datetime import date, datetime
from typing import Annotated, Any

import pandas as pd
from pydantic import BeforeValidator, model_validator

from gemini._utils.time import to_utc
from gemini.case._utils.fields import Q, Shape
from gemini.case._utils.section import Section
from gemini.errors import ValidationError


def _instant(value):
    """Return a UTC ``Timestamp`` of a date, a datetime or ISO-8601 text; naive is UTC."""
    if value is None:
        return None
    try:
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime(value.year, value.month, value.day)
        return pd.Timestamp(to_utc(value))
    except (TypeError, ValueError) as error:
        raise ValidationError(
            f"value = {value!r}; expected an ISO-8601 date such as '2027-01-01'",
            code="invalid_value",
        ) from error


Instant = Annotated[Any, BeforeValidator(_instant), Shape({"type": "string", "format": "date"})]


class Time(Section):
    """The period of a run: ``start``, ``end`` and ``step``.

    ``end`` is excluded, so ``2027-01-01`` to ``2028-01-01`` at one day is 365 steps. Every
    profile of the case lies on ``Time.index``. ``start`` and ``end`` are UTC timestamps (a naive
    date is UTC) and ``step`` a duration in seconds.

    Attributes
    ----------
    start, end : Timestamp
        First instant and end, UTC.
    step : float
        Step [s].
    """

    where = "time"
    start: Instant
    end: Instant
    step: Annotated[Any, Q("duration", minimum=(0.0, True))]

    @model_validator(mode="after")
    def _ordered(self):
        """Refuse an end that does not follow the start by whole steps."""
        seconds = (self.end - self.start).total_seconds()
        if seconds <= 0:
            raise ValidationError(
                f"end = {self.end.date()}; expected a date after start = {self.start.date()}",
                code="out_of_bounds",
            )
        if seconds % self.step:
            raise ValidationError(
                f"step = {self.step} s does not divide the period of {seconds} s; expected a "
                "whole number of steps between start and end",
                code="invalid_value",
            )
        return self

    @property
    def index(self):
        """The instants of the run: a UTC ``DatetimeIndex`` called ``time``, ``end`` excluded."""
        step = pd.Timedelta(seconds=self.step)
        return pd.date_range(self.start, self.end, freq=step, inclusive="left", name="time")

    def to_dict(self):
        """Return the time as plain data; a date at midnight is written as a date."""
        return super().to_dict() | {"start": _text(self.start), "end": _text(self.end)}


def _text(instant):
    """Return the ISO text of ``instant``: a date at midnight, else the full time."""
    midnight = instant == instant.normalize()
    return instant.date().isoformat() if midnight else instant.isoformat()
