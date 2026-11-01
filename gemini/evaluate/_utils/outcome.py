"""What an economics function does when the inputs cannot give its value.

Every function raises by default. With ``on_error="record"`` nothing is raised: the value is
``None`` with a ``reason``. ``reported`` wraps the computation and ``unavailable`` is the end of
one that finds no value; the functions call each other with ``"record"`` and read the ``None``.
"""

from gemini.errors import GeminiError, ValidationError
from gemini.errors.base import check_on_error
from gemini.types.shapes import measure


def unavailable(unit, reason, on_error, **details):
    """Raise that the inputs cannot give a value, or return it as ``None`` with the ``reason``."""
    if on_error == "raise":
        raise ValidationError(reason, code="no_value")
    return measure(None, unit, reason, **details)


def reported(on_error, unit, compute):
    """Return ``compute()``; under ``on_error="record"`` its failure is a value ``None``."""
    check_on_error(on_error)
    try:
        return compute()
    except GeminiError as error:
        if on_error == "raise":
            raise
        return measure(None, unit, str(error))
