"""``Failed``: the value of a physics function whose ``check`` failed in an eager scope.

``ops.check`` cannot attach an error to a value it returns nothing for. On concrete scalars it
raises the real error marked as coming from a check (``mark``); ``ops.physics`` catches a marked
error at the function's boundary and returns ``Failed(error)`` instead, so that
``where(stopped, 0.0, checked_function(x))`` drops the error when ``stopped`` selects the other
branch, exactly as the graph's error codes do. A ``Failed`` is a ``Symbolic``: every op, operator,
``Constant`` and NumPy scalar operation that meets it returns it. ``where`` is the exception: a
concrete condition selects a branch and an error in the other branch is dropped, while a
``Failed`` condition stays failed. ``bool()``, ``float()``, ``int()`` and ``format()`` raise the
error, so a structural ``if``, a ``Stream`` or a ``Declaration`` surface it, and so does leaving
the outermost scope (``ops.scope.plain``).
"""

from gemini.ops.dispatch import Operators, Symbolic
from gemini.ops.failures import next_order

MARK = "_gemini_check"
ORDER = "_gemini_order"


def mark(error):
    """Mark ``error`` as raised by a failing ``ops.check`` and return it."""
    setattr(error, MARK, True)
    setattr(error, ORDER, next_order())
    return error


def is_marked(error):
    """Return whether ``error`` was raised by a failing ``ops.check``."""
    return getattr(error, MARK, False)


class Failed(Operators, Symbolic):
    """A value that stands for a failed check; ``error`` is the exception it raises if used."""

    def __init__(self, error):
        """Hold the ``error`` of the failing check; ``order`` is when the check failed."""
        self.error = error
        self.order = getattr(error, ORDER, 0)

    def record(self, definition, operands, attributes=None):
        """Return the earliest failure among the operands; ``where`` picks its selected branch.

        The graph raises the lowest check code whatever the operand order, so of two failures the
        one whose check ran first is kept. A concrete ``where`` condition selects a branch and
        drops an error in the other; a failed condition stays failed.
        """
        if definition.name == "where":
            return _selected(*operands)
        failures = [operand for operand in operands if isinstance(operand, Failed)]
        return min(failures, key=lambda failure: failure.order, default=self)

    def __repr__(self):
        """Return ``Failed(ErrorClass: message)`` without raising."""
        return f"Failed({type(self.error).__name__}: {self.error})"

    def __float__(self):
        """Raise the error."""
        raise self.error

    def __int__(self):
        """Raise the error."""
        raise self.error

    def __bool__(self):
        """Raise the error."""
        raise self.error

    def __format__(self, data):
        """Raise the error."""
        raise self.error

    def __eq__(self, other):
        """Return this failure."""
        return self

    def __ne__(self, other):
        """Return this failure."""
        return self

    __hash__ = object.__hash__

    def __and__(self, other):
        """Return this failure."""
        return self

    __rand__ = __or__ = __ror__ = __xor__ = __rxor__ = __and__

    def __invert__(self):
        """Return this failure."""
        return self

    def __getitem__(self, index):
        """Return this failure."""
        return self


def _selected(condition, if_true, if_false):
    """Return the failed condition, else the branch a concrete condition selects."""
    if isinstance(condition, Symbolic):
        return condition
    return if_true if condition else if_false
