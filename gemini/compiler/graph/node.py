"""One node of a computation graph: a graph input or one op applied to earlier nodes."""

import sys
from dataclasses import dataclass, field
from pathlib import Path

from gemini.types import flows

_TRACING_PACKAGES = tuple(
    str(Path(__file__).parents[2] / package)
    for package in ("compiler/graph", "ops", "modules/_utils")
)


STREAM_FIELDS = tuple(zip(flows.STREAM_FIELDS, ("kg/s", "K", "Pa")))
"""Stream fields of every inlet and outlet in the graph, with their units."""


@dataclass(eq=False, slots=True)
class Node:
    """A graph input (``op == "input"``) or one op applied to ``operands``.

    ``operands`` holds earlier nodes and literal numbers. Inputs carry a ``name``, a ``role``
    (``inlet``, ``control``, ``boundary``, ``parameter`` or ``constant``), a ``unit`` and the
    ``shape`` of one row (``()`` or ``(n,)`` for a vector parameter). A ``check`` node carries
    its error class, message and message values in ``attributes`` and its error ``code``.
    ``guards`` lists the check nodes whose errors travel with this node's value. ``source`` is
    the file and line of the physics code that created the node.
    """

    index: int
    op: str
    kind: str
    operands: tuple = ()
    name: str | None = None
    role: str | None = None
    unit: str | None = None
    shape: tuple = ()
    attributes: dict | None = None
    code: int = 0
    guards: list = field(default_factory=list)
    source: str = ""

    def label(self):
        """Return ``%index`` with the input name, for graph listings."""
        return f"%{self.index}" + (f"<{self.name}>" if self.name else "")


def caller_source():
    """Return ``file:line`` of the innermost frame outside the tracing packages."""
    frame = sys._getframe(1)
    while frame is not None and frame.f_code.co_filename.startswith(_TRACING_PACKAGES):
        frame = frame.f_back
    if frame is None:
        return ""
    return f"{frame.f_code.co_filename}:{frame.f_lineno}"
