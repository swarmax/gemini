"""The seven public classes, the fixed lists of codes and the shape of a problem."""

CODES = (
    "error",
    "invalid_value",
    "conflicting_value",
    "out_of_bounds",
    "missing_value",
    "no_value",
    "missing_assumption",
    "invalid_unit",
    "unknown_name",
    "duplicate_name",
    "unknown_port",
    "invalid_call",
    "invalid_format",
    "old_format",
    "migration_failed",
    "invalid_connection",
    "stream_mismatch",
    "ambiguous_port",
    "port_in_use",
    "unconnected_port",
    "root_plant_port",
    "invalid_binding",
    "missing_column",
    "invalid_data",
    "inputs_missing",
    "invalid_design",
    "invalid_definition",
    "out_of_range",
    "no_convergence",
    "loop_not_converged",
    "missing_chemistry",
    "too_little_data",
    "clock",
    "checkpoint",
    "step",
    "cancelled",
    "not_implemented",
)
"""Every value of ``GeminiError.code``; the backend puts them into ``422`` details."""

ROW_CODES = {
    "missing_value": "A bound column has no finite value at this tick; the row was skipped.",
    "invalid_inlet": "An inlet stream breaks the stream limits; the row failed.",
    "out_of_bounds": "A control, boundary or output is outside its bounds; the row failed.",
    "out_of_range": "An input is outside the domain of a correlation; the row failed.",
    "no_convergence": "An iterative solve did not converge; the row failed.",
    "module_error": "A module raised any other error; the row failed.",
}
"""Every row code of ``Results.errors()`` with its meaning."""

ON_ERROR = ("raise", "record")
"""The values of ``on_error``, the one argument of a call that can report instead of raising."""


def problem(path, code, message, suggestions=(), time=None):
    """Return the shape ``{path, code, message, suggestions}`` of every problem as plain JSON.

    A failed run row adds ``time``. The one helper of the shape, here because ``gemini.errors`` is
    a leaf package and ``to_dict`` returns one; ``gemini.types.shapes`` exports it with the others.
    """
    shape = {"path": path, "code": code, "message": str(message), "suggestions": list(suggestions)}
    return shape if time is None else shape | {"time": time}


class GeminiError(Exception):
    """Base class of every error GEMINI raises on purpose; catch it to handle them all.

    ``path`` says where the problem is (a dotted module path or a path into a data),
    ``suggestions`` lists close valid names and ``code`` is one of ``CODES``, by default the
    class attribute. ``to_dict`` gives the JSON form used in ``422`` details and tool results.
    ``problems`` lists every problem as such a dictionary: all of them when the error comes from
    several, the one of ``to_dict`` otherwise.
    """

    code = "error"
    path = None
    suggestions = ()

    def __init__(self, *args, path=None, code=None, suggestions=(), problems=()):
        """Keep the message and the optional location, code, close-match names and problems."""
        super().__init__(*args)
        if code is not None:
            if code not in CODES:
                raise GeminiError(f"GeminiError: code = {code!r}; expected one of CODES")
            self.code = code
        if path is not None:
            self.path = path
        if suggestions:
            self.suggestions = tuple(suggestions)
        self._problems = list(problems)

    @property
    def problems(self):
        """Every problem of this error, the list ``on_error="record"`` returns."""
        return self._problems or [self.to_dict()]

    def to_dict(self):
        """Return the problem ``{path, code, message, suggestions}`` as plain JSON."""
        return problem(self.path, self.code, self, self.suggestions)


class GeminiWarning(UserWarning):
    """Base class of every warning GEMINI emits."""


class ValidationError(GeminiError, ValueError):
    """Wrong input: a value, a dict, a binding, a unit or an unknown name."""

    code = "invalid_value"

    @classmethod
    def of(cls, problems):
        """Return the one error of a non-empty list of problems, carried in ``problems``."""
        first = problems[0]
        message = "; ".join(
            f"{item['path']}: {item['message']}" if item["path"] else item["message"]
            for item in problems
        )
        return cls(
            message,
            path=first["path"],
            code=first["code"],
            suggestions=first["suggestions"],
            problems=problems,
        )


class DefinitionError(GeminiError):
    """A module class written wrongly: declarations, children, hooks, formulas or outlets."""

    code = "invalid_definition"


class PhysicsError(GeminiError):
    """Out of range, no convergence, missing chemistry or too little data."""

    code = "out_of_range"


class RunError(GeminiError):
    """A dataset, a clock, a checkpoint or a step of a run failed."""

    code = "step"


class Cancelled(GeminiError):
    """A callback stopped a run; the ticks already committed stay readable."""

    code = "cancelled"


class NotImplementedYet(GeminiError):
    """The name is final but its work lands in a later step."""

    code = "not_implemented"


def check_on_error(on_error):
    """Refuse a value of ``on_error`` other than ``"raise"`` and ``"record"``."""
    if on_error not in ON_ERROR:
        raise ValidationError(
            f"on_error = {on_error!r}; expected 'raise' or 'record'", path="on_error"
        )


def reported(problems, on_error):
    """Return ``problems`` under ``on_error="record"``; else raise them, if there are any."""
    check_on_error(on_error)
    if problems and on_error == "raise":
        raise ValidationError.of(problems)
    return problems
