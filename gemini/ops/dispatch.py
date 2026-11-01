"""Op dispatch: record an op on traced values, otherwise evaluate it on a backend.

``dispatch(name, *operands)`` is the single entry of every op. When an operand is
``Symbolic`` (a traced value of the compiler), the op is recorded in its graph.
Otherwise every ``Constant`` operand is replaced by its plain Python value and the op runs on
the backend that ``gemini.ops.kernels.select`` chooses. ``Operators`` gives a class the Python
operators through the same entry.
"""

import numpy as np

from gemini.ops import kernels, registry

SCALARS = frozenset({float, int, bool, type(None), np.float64, np.int64, np.bool_})
"""Exact types of the scalars of the fast path: Python numbers, ``None`` (a ``where`` branch)
and the NumPy scalars of the eager scope and of arithmetic on rows of a dataset."""

_PYTHON = kernels.get("python")


class Symbolic:
    """Base of traced values: an op with a ``Symbolic`` operand is recorded, not evaluated."""

    def record(self, definition, operands, attributes=None):
        """Record ``definition`` applied to ``operands`` and return the traced result."""
        raise NotImplementedError(f"{type(self).__name__} does not record ops")


def dispatch(name, *operands, attributes=None):
    """Apply the op ``name`` to ``operands``: record it on traced values, else evaluate it."""
    for operand in operands:
        if isinstance(operand, Symbolic):
            return operand.record(registry.get(name), operands, attributes)
    values = tuple(
        operand.value if isinstance(operand, Constant) else operand for operand in operands
    )
    method = kernels.implementation(kernels.select(values), name)
    return method(*values, **(attributes or {}))


def elementwise_op(name, arity, summary):
    """Register the elementwise op ``name`` and return its function, cheap on plain scalars.

    The function evaluates scalars of the types in ``SCALARS`` (exact types, never subclasses)
    directly on the Python backend's method, resolved once here, as long as no
    ``runtime.settings(backend=...)`` is active. Anything else (arrays, NumPy scalars,
    ``Constant``, traced values, a forced backend) goes through ``dispatch``.
    """
    registry.register(name, "elementwise", arity)
    method = getattr(_PYTHON, name)
    if arity == 1:

        def unary(value):
            if type(value) in SCALARS and kernels.forced_name() is None:
                return method(value)
            return dispatch(name, value)

        return _described(unary, name, summary)
    if arity == 2:

        def binary(left, right):
            if type(left) in SCALARS and type(right) in SCALARS and kernels.forced_name() is None:
                return method(left, right)
            return dispatch(name, left, right)

        return _described(binary, name, summary)

    def ternary(first, second, third):
        if (
            type(first) in SCALARS
            and type(second) in SCALARS
            and type(third) in SCALARS
            and kernels.forced_name() is None
        ):
            return method(first, second, third)
        return dispatch(name, first, second, third)

    return _described(ternary, name, summary)


def _described(function, name, summary):
    function.__name__ = function.__qualname__ = name
    function.__doc__ = summary
    return function


class Operators:
    """Python arithmetic and comparison operators that dispatch to the ops."""

    __array_ufunc__ = None

    def __add__(self, other):
        """Return ``self + other``."""
        return dispatch("add", self, other)

    def __radd__(self, other):
        """Return ``other + self``."""
        return dispatch("add", other, self)

    def __sub__(self, other):
        """Return ``self - other``."""
        return dispatch("sub", self, other)

    def __rsub__(self, other):
        """Return ``other - self``."""
        return dispatch("sub", other, self)

    def __mul__(self, other):
        """Return ``self * other``."""
        return dispatch("mul", self, other)

    def __rmul__(self, other):
        """Return ``other * self``."""
        return dispatch("mul", other, self)

    def __truediv__(self, other):
        """Return ``self / other``."""
        return dispatch("truediv", self, other)

    def __rtruediv__(self, other):
        """Return ``other / self``."""
        return dispatch("truediv", other, self)

    def __pow__(self, other):
        """Return ``self ** other``."""
        return dispatch("pow", self, other)

    def __rpow__(self, other):
        """Return ``other ** self``."""
        return dispatch("pow", other, self)

    def __mod__(self, other):
        """Return ``self % other``."""
        return dispatch("mod", self, other)

    def __rmod__(self, other):
        """Return ``other % self``."""
        return dispatch("mod", other, self)

    def __floordiv__(self, other):
        """Return ``self // other``."""
        return dispatch("floordiv", self, other)

    def __rfloordiv__(self, other):
        """Return ``other // self``."""
        return dispatch("floordiv", other, self)

    def __neg__(self):
        """Return ``-self``."""
        return dispatch("neg", self)

    def __abs__(self):
        """Return ``abs(self)``."""
        return dispatch("abs", self)

    def __lt__(self, other):
        """Return ``self < other``."""
        return dispatch("lt", self, other)

    def __le__(self, other):
        """Return ``self <= other``."""
        return dispatch("le", self, other)

    def __gt__(self, other):
        """Return ``self > other``."""
        return dispatch("gt", self, other)

    def __ge__(self, other):
        """Return ``self >= other``."""
        return dispatch("ge", self, other)


class Constant:
    """A named physical or model constant: fixed by default, a named graph input when traced.

    On concrete values a constant acts exactly like its Python float, including NumPy's
    weak-scalar promotion, so ``np.float32(x) / constant`` stays float32. It is deliberately not
    a ``float`` subclass, which NumPy 2 would promote to float64. Its operators compute on
    ``value`` directly, without ``dispatch``, unless the other operand is ``Symbolic``: then the
    op is recorded and the constant becomes one graph input named ``name``, so a sensitivity
    study can release it without retracing. As with floats, ``/``, ``//``, ``%`` and ``**`` on
    invalid operands raise outside an eager scope; inside one (``gemini.ops.scope``) the operators
    compute on ``np.float64`` and are silent like the ops.
    """

    __slots__ = ("name", "value", "unit", "description", "_scalar")
    __array_ufunc__ = None

    def __init__(self, name, value, unit, description):
        """Declare a constant with its SI ``value`` and ``unit``."""
        self.name = name
        self.value = float(value)
        self._scalar = np.float64(value)
        self.unit = unit
        self.description = description

    def _number(self):
        """Return the value as ``np.float64`` inside a wrapping eager scope, else as ``float``."""
        return self._scalar if kernels.scope_mode() is kernels.WRAP else self.value

    def __float__(self):
        """Return the value."""
        return self.value

    def __format__(self, data):
        """Format the value."""
        return format(self.value, data)

    def __repr__(self):
        """Return ``Constant(name=value unit)``."""
        return f"Constant({self.name}={self.value!r} {self.unit})"

    def __add__(self, other):
        """Return ``self + other``."""
        if isinstance(other, Symbolic):
            return dispatch("add", self, other)
        return self._number() + other

    def __radd__(self, other):
        """Return ``other + self``."""
        if isinstance(other, Symbolic):
            return dispatch("add", other, self)
        return other + self._number()

    def __sub__(self, other):
        """Return ``self - other``."""
        if isinstance(other, Symbolic):
            return dispatch("sub", self, other)
        return self._number() - other

    def __rsub__(self, other):
        """Return ``other - self``."""
        if isinstance(other, Symbolic):
            return dispatch("sub", other, self)
        return other - self._number()

    def __mul__(self, other):
        """Return ``self * other``."""
        if isinstance(other, Symbolic):
            return dispatch("mul", self, other)
        return self._number() * other

    def __rmul__(self, other):
        """Return ``other * self``."""
        if isinstance(other, Symbolic):
            return dispatch("mul", other, self)
        return other * self._number()

    def __truediv__(self, other):
        """Return ``self / other``."""
        if isinstance(other, Symbolic):
            return dispatch("truediv", self, other)
        return self._number() / other

    def __rtruediv__(self, other):
        """Return ``other / self``."""
        if isinstance(other, Symbolic):
            return dispatch("truediv", other, self)
        return other / self._number()

    def __pow__(self, other):
        """Return ``self ** other``."""
        if isinstance(other, Symbolic):
            return dispatch("pow", self, other)
        return self._number() ** other

    def __rpow__(self, other):
        """Return ``other ** self``."""
        if isinstance(other, Symbolic):
            return dispatch("pow", other, self)
        return other ** self._number()

    def __mod__(self, other):
        """Return ``self % other``."""
        if isinstance(other, Symbolic):
            return dispatch("mod", self, other)
        return self._number() % other

    def __rmod__(self, other):
        """Return ``other % self``."""
        if isinstance(other, Symbolic):
            return dispatch("mod", other, self)
        return other % self._number()

    def __floordiv__(self, other):
        """Return ``self // other``."""
        if isinstance(other, Symbolic):
            return dispatch("floordiv", self, other)
        return self._number() // other

    def __rfloordiv__(self, other):
        """Return ``other // self``."""
        if isinstance(other, Symbolic):
            return dispatch("floordiv", other, self)
        return other // self._number()

    def __lt__(self, other):
        """Return ``self < other``."""
        if isinstance(other, Symbolic):
            return dispatch("lt", self, other)
        return self.value < other

    def __le__(self, other):
        """Return ``self <= other``."""
        if isinstance(other, Symbolic):
            return dispatch("le", self, other)
        return self.value <= other

    def __gt__(self, other):
        """Return ``self > other``."""
        if isinstance(other, Symbolic):
            return dispatch("gt", self, other)
        return self.value > other

    def __ge__(self, other):
        """Return ``self >= other``."""
        if isinstance(other, Symbolic):
            return dispatch("ge", self, other)
        return self.value >= other

    def __neg__(self):
        """Return ``-self``."""
        return -self._number()

    def __abs__(self):
        """Return ``abs(self)``."""
        return abs(self._number())
