"""The op registry: the name, kind and operand count of every op.

The registry only describes ops; backends implement them (``gemini.ops.kernels``) and the graph
records them. The kind is what graph passes rely on: ``elementwise`` ops apply row by row,
``index`` selects one item of a vector parameter, ``check`` produces per-row error codes,
``solver`` ops (``brentq``, ``newton``) find roots with per-row stopping and keep their function
and settings in node attributes (the arity counts the fixed operands, ``args`` follow), and
``scan`` carries state from step to step. A ``break`` node runs one module that cannot be
traced, row by row on the plain path; its outputs are ``break_output`` nodes. A ``loop`` node is
the masked fixed point of a plant loop: its body runs inside the interpreter, pass by pass.
"""

from dataclasses import dataclass

from gemini._utils.strings import did_you_mean
from gemini.errors import ValidationError

KINDS = ("elementwise", "index", "reduction", "interp", "check", "solver", "scan", "break", "loop")

_OPS = {}


@dataclass(frozen=True)
class OpDef:
    """One registered op: its ``name``, ``kind`` and number of operands ``arity``."""

    name: str
    kind: str
    arity: int


def register(name, kind, arity):
    """Register an op and return its definition; the kind must be one of ``KINDS``."""
    if kind not in KINDS:
        raise ValidationError(
            f"ops.register: kind = {kind!r}; expected one of {KINDS}", code="unknown_name"
        )
    _OPS[name] = OpDef(name, kind, arity)
    return _OPS[name]


def get(name):
    """Return the definition of the op called ``name``."""
    if name not in _OPS:
        raise ValidationError(
            f"ops: op = {name!r} is unknown{did_you_mean(name, _OPS)}", code="unknown_name"
        )
    return _OPS[name]


def registered():
    """Return every op definition by name, in registration order."""
    return dict(_OPS)
