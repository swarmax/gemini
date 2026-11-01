"""The eager physics scope: ``@ops.physics`` and the scope a module call enters.

A direct call of a module or a physics function is eager: the same ``forward`` and the same ops
as the graph, evaluated on the Python backend. One mechanism makes plain operators safe there:

- **Entering the outermost scope** enters ``np.errstate(all="ignore")`` and gives a function called
  on plain Python numbers its arguments as NumPy scalars: an exact ``float`` as ``np.float64``, an
  exact ``int`` as ``np.int64``, which prints, indexes and loops as an int (``bool``, ``None``,
  strings, arrays and traced values pass through). They have the arithmetic of Python numbers
  but ``/`` by zero, an invalid ``**`` and an overflow give ``inf`` or ``nan`` silently, like the
  NumPy and graph backends. Arrays or traced values among the arguments leave the scope unwrapped
  (an ``np.float64`` scalar would promote a float32 array), and so does a module whose
  ``Module._scalar_mode`` is ``PLAIN`` (the ESP under float32 precision, the one quirk).
- **Nested scopes** only wrap the exact numbers among their own arguments (a literal ``0.0``) and
  catch a failing check; the cost is a ``ContextVar`` read and a scan of the arguments.
- **Leaving the outermost scope** returns plain Python scalars on every backend: ``float`` for
  ``np.float64``, ``bool`` for ``np.bool_``, recursively through tuples, lists, dicts and frozen
  dataclasses, and raises the error of a ``Failed`` found anywhere in the result.
- **A failing check** (``ops.check`` on concrete scalars) raises a marked error; ``physics``
  returns ``Failed(error)`` for it at each function boundary (see ``gemini.ops.failed``).
  Outside any scope the caller sees the real error. A failing check on an eager array raises at
  once, for its first failing row, and is never turned into a ``Failed``; the eager executor asks
  for ``gemini.ops.failures.marking`` instead, and then the failing rows of a physics function
  travel with its results as ``FailedRows``, the array counterpart of ``Failed``.
- **In a trace** (``tracing(graph)``) a physics function keeps the checks recorded directly in it
  and guards every traced value it returns with them, so the graph attaches an error to the
  results of the function exactly as the eager ``Failed`` does. A check recorded outside any
  physics function is certain: it guards every graph output, as it raises at once when eager.
- **A result used for its validity only** is passed to ``require``, or its error is dropped.

Do not put ``repr`` of a physical value in a message (``np.float64(1.0)``), and note that
``round(np.float64, n)`` is NumPy's rounding: use ``ops.round``.
"""

import dataclasses
from contextvars import ContextVar
from functools import wraps

import numpy as np

from gemini._utils.context import ContextSetting
from gemini.ops.dispatch import Symbolic
from gemini.ops.failed import Failed, is_marked
from gemini.ops.failures import Frame, is_marking
from gemini.ops.failures import require as require_rows
from gemini.ops.kernels import PLAIN, WRAP
from gemini.ops.kernels.scalars import scope_mode, scope_variable

_NUMBERS = frozenset({float, int})
_PASS = frozenset({np.float64, np.int64, bool, str, type(None), np.bool_})
_ATOMIC = frozenset({float, int, bool, str, type(None), np.ndarray})
_CONVERT = {np.float64: float, np.int64: int, np.bool_: bool}
_LARGEST_INT = 2**63 - 1


_traced = ContextVar("gemini_traced_graph", default=None)


def tracing(graph):
    """Select ``graph`` as the one that physics functions record their checks in."""
    return ContextSetting(_traced, lambda current: graph)


def traced_graph():
    """Return the graph the running trace records into, ``None`` outside a trace."""
    return _traced.get()


def _scalar(value):
    """Return an exact ``float`` or ``int`` as its NumPy scalar; an int beyond 64 bits stays."""
    kind = type(value)
    if kind is float:
        return np.float64(value)
    if kind is int and abs(value) <= _LARGEST_INT:
        return np.int64(value)
    return value


def wrap(value):
    """Return ``value`` for the scope: numbers as NumPy scalars; lists, tuples and dicts too."""
    kind = type(value)
    if kind in _NUMBERS:
        return _scalar(value)
    if kind is list or kind is tuple:
        return kind(wrap(item) for item in value)
    if kind is dict:
        return {key: wrap(item) for key, item in value.items()}
    return value


def plain(value):
    """Return ``value`` as plain Python scalars; raise the error of any ``Failed`` inside it."""
    kind = type(value)
    if kind in _ATOMIC:
        return value
    converter = _CONVERT.get(kind)
    if converter is not None:
        return converter(value)
    if isinstance(value, Failed):
        raise value.error
    if kind is list or kind is tuple:
        return kind(plain(item) for item in value)
    if kind is dict:
        return {key: plain(item) for key, item in value.items()}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _plain_dataclass(value)
    return value


def _plain_dataclass(value):
    """Return the dataclass ``value`` with plain fields, itself when nothing changes."""
    changes = {}
    for field in dataclasses.fields(value):
        item = getattr(value, field.name)
        converted = plain(item)
        if converted is not item:
            changes[field.name] = converted
    return dataclasses.replace(value, **changes) if changes else value


def _wrapped(values):
    """Return ``values`` with exact numbers as NumPy scalars; ``None`` if any is array or traced.

    A 0-d array, what ops give under a forced NumPy backend, counts as a scalar.

    ``values`` is a sequence; ``None`` also stands for "leave the call unwrapped".
    """
    converted = []
    for value in values:
        kind = type(value)
        if kind in _NUMBERS or kind is dict:
            converted.append(wrap(value))
            continue
        if kind is np.ndarray and value.ndim == 0:
            converted.append(value)
            continue
        if kind not in _PASS and isinstance(value, (np.ndarray, Symbolic)):
            return None
        converted.append(value)
    return converted


def _wrapped_call(args, kwargs):
    """Return ``(args, kwargs, wrapped)`` with exact numbers wrapped; unchanged for arrays."""
    positional = _wrapped(args)
    named = _wrapped(kwargs.values())
    if positional is None or named is None:
        return args, kwargs, False
    return tuple(positional), dict(zip(kwargs, named)), True


class Scope:
    """Context manager entering the eager scope for a call that asks for ``mode``.

    ``arrays`` says that the call holds arrays or traced values, which leaves it unwrapped. The
    first entry also opens ``np.errstate``. Every entry sets the mode of the scope for its own
    duration and restores the previous one on exit, so a module that wants ``PLAIN`` inside a
    wrapping composite behaves as it did before. After ``__enter__``, ``wrapping`` tells whether
    this call wraps scalars and ``outermost`` whether it opened the scope.
    """

    __slots__ = ("mode", "arrays", "wrapping", "outermost", "_token", "_errstate")

    def __init__(self, mode=WRAP, arrays=False):
        """Prepare a scope asking for ``mode``; arrays or traced values force ``PLAIN``."""
        self.mode = PLAIN if arrays else mode
        self.wrapping = self.mode is WRAP
        self.outermost = False

    def __enter__(self):
        """Enter the scope, opening ``np.errstate`` if none is running."""
        self.outermost = scope_mode() is None
        if self.outermost:
            self._errstate = np.errstate(all="ignore")
            self._errstate.__enter__()
        self._token = scope_variable.set(self.mode)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Restore the mode that was running, and leave ``np.errstate`` if this entry opened it."""
        scope_variable.reset(self._token)
        if self.outermost:
            self._errstate.__exit__(exc_type, exc_value, traceback)


def physics(function):
    """Decorate a public function of ``gemini/physics`` so it is safe with plain operators.

    The outermost call opens the scope (silent NumPy arithmetic, ``np.float64`` arguments, plain
    scalars and ``Failed`` handling on return); a nested call wraps its own exact floats and
    returns ``Failed`` where a ``check`` failed. In a trace, whatever the mode, the checks of the
    function guard its results.
    """

    @wraps(function)
    def wrapper(*args, **kwargs):
        mode = scope_mode()
        if mode is None:
            return _outermost(function, args, kwargs)
        failed = _first_failed(args, kwargs)
        if failed is not None:
            return failed
        if mode is WRAP:
            args, kwargs = _wrapped_nested(args, kwargs)
        try:
            if mode is PLAIN and is_marking():
                return _marked(function, args, kwargs)
            return _framed(function, args, kwargs)
        except Exception as error:
            if not is_marked(error):
                raise
            return Failed(error)

    return wrapper


def _marked(function, args, kwargs):
    """Call ``function`` and give its results the rows its array checks failed."""
    with Frame() as frame:
        result = _framed(function, args, kwargs)
    return frame.result(result)


def _wrapped_nested(args, kwargs):
    """Return the arguments of a nested call with their exact numbers as NumPy scalars."""
    return tuple(map(_scalar, args)), {name: _scalar(value) for name, value in kwargs.items()}


def _first_failed(args, kwargs):
    """Return a ``Failed`` argument, so a function never runs on a value that has failed."""
    for value in args:
        if type(value) is Failed:
            return value
    for value in kwargs.values():
        if type(value) is Failed:
            return value
    return None


def require(value):
    """Surface the error of ``value`` where its number is not used, as if it reached an output.

    A failed result that nothing reads is dropped on every backend. ``forward`` calls this for a
    physics result it computes only for its validity: a ``Failed`` raises and, in a trace, the
    traced values of ``value`` become graph outputs, so a failing row fails.
    """
    if isinstance(value, Failed):
        raise value.error
    if is_marking():
        require_rows(value)
    graph = _traced.get()
    if graph is not None:
        graph.require(value)


def _outermost(function, args, kwargs):
    """Run ``function`` in a new scope and return its result as plain scalars."""
    wrapped_args, wrapped_kwargs, wrapping = _wrapped_call(args, kwargs)
    with Scope(arrays=not wrapping) as scope:
        if scope.wrapping:
            args, kwargs = wrapped_args, wrapped_kwargs
        elif is_marking():
            return plain(_marked(function, args, kwargs))
        return plain(_framed(function, args, kwargs))


def _framed(function, args, kwargs):
    """Call ``function``; in a trace, guard its traced results with the checks it recorded."""
    graph = _traced.get()
    if graph is None:
        return function(*args, **kwargs)
    start = graph.open_frame()
    try:
        result = function(*args, **kwargs)
    except Exception as error:
        graph.abandon_frame()
        if is_marked(error):
            raise graph.constant_failure(function.__name__, error) from error
        raise
    return graph.close_frame(result, start)
