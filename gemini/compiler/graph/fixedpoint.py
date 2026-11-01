"""Evaluate a ``fixed_point`` node: iterate the body of a loop on arrays, masked per row.

The iteration is ``gemini.plants._utils.loops.iterate``, the one that closes a loop on a plain
call; this module only gives it a pass that runs the nodes of the body. Each pass sets the
carries to the iterates of the trial, evaluates the body, finds the rows that got an error into
an outlet of a step (``Body.watch``) or failed a check of no physics function (``Body.unframed``)
and returns the images of the tear fields. The error codes of everything before the node seed
those of the body, so a row that arrives with an error stops at its first pass.
"""

import numpy as np

from gemini.compiler.graph.codes import NONE
from gemini.plants._utils import loops
from gemini.types.flows import STREAM_FIELDS as NAMES
from gemini.types.flows import Stream


class FixedPoint:
    """The converged iterates of a loop, by carry index, and the rows that did not converge."""

    def __init__(self, tears, active):
        """Keep the current value of every field of ``tears`` and ``active``."""
        self.columns = {
            index: field.current
            for index, field in enumerate(f for tear in tears for f in tear.fields.values())
        }
        self.columns["active"] = active

    def column(self, key):
        """Return the value of a carry by index, or the rows still active for ``"active"``."""
        return self.columns[key]


def evaluate_loop(interpreter, node, operands, values, feeds):
    """Run the body of the ``fixed_point`` ``node`` until the rows settle; return its values."""
    attributes = node.attributes
    body = attributes["body"]
    lower, upper = operands[-2:]
    tears = _tears(attributes["fluids"], operands[:-2], lower, upper)
    seed = interpreter.errors_before(node, values)
    interpreter.seeds[body] = seed

    def around(tears):
        carried = [value for tear in tears for value in tear.values(True).values()]
        values.update(zip(body.carries, carried))
        interpreter.run_nodes(body.nodes, values, feeds)
        errors = interpreter.propagate(body.nodes, body.checks, values, seed)
        found = [_read(operand, values) for operand in body.images]
        images = [
            Stream._trusted(**dict(zip(NAMES, found[start : start + 3])), fluid=fluid)
            for start, fluid in zip(range(0, len(found), 3), attributes["fluids"])
        ]
        return images, _failed(body, values, errors)

    active = loops.iterate(tears, attributes["tolerance"], attributes["passes"], around)
    return FixedPoint(tears, active)


def _tears(fluids, starts, lower, upper):
    return [
        loops.Tear(
            Stream._trusted(**dict(zip(NAMES, starts[index : index + 3])), fluid=fluid),
            lower,
            upper,
        )
        for index, fluid in zip(range(0, len(starts), 3), fluids)
    ]


def _read(operand, values):
    return values[operand] if hasattr(operand, "index") else operand


def _failed(body, values, errors):
    """Return the rows with an error in a watched node or a failed check of no function."""
    failed = False
    for check in body.unframed:
        failed = np.logical_or(failed, values[check] != 0)
    for node in body.watch:
        code = errors.get(node)
        if code is not None:
            failed = np.logical_or(failed, code != NONE)
    return failed
