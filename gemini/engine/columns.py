"""The data one twin reads over a stretch of ticks, converted to SI, and what each tick lacks.

``read`` turns the bound columns of a ``Twin`` into SI arrays over ``[start, stop)`` and gives
every row a ``status`` in the order a plain call would meet its problems: the first missing
observation (a skip, counted by its reason), or an inlet stream the limits refuse (an error,
built by the real ``Stream`` constructor). A row with status ``0`` can be evaluated. A control
set on the module before its state is read keeps its inputs when only a state is missing
(``late``), as the module's own order of work does.
"""

from dataclasses import dataclass, field

import numpy as np

from gemini import units
from gemini.engine.step import VOLUMETRIC_UNITS
from gemini.types import Fluid, Stream
from gemini.types.flows import STREAM_FIELDS, mass_flow, stream_valid


@dataclass
class Block:
    """The SI values of one twin over ``size`` ticks and the status of every tick.

    ``status`` is ``0`` for a tick that can be evaluated, ``k > 0`` for a skip with reason
    ``reasons[k - 1]`` and ``-k`` for an invalid stream at inlet ``ports[k - 1]``. ``inputs``
    maps feed names to arrays, ``fields`` maps ``(port, field)`` to arrays, ``measured`` and
    ``states`` map names to arrays. ``late`` lists the skip statuses of missing states.
    """

    size: int
    status: np.ndarray
    reasons: list
    ports: list
    inputs: dict = field(default_factory=dict)
    fields: dict = field(default_factory=dict)
    fluids: dict = field(default_factory=dict)
    measured: dict = field(default_factory=dict)
    states: dict = field(default_factory=dict)
    late: tuple = ()

    @property
    def selected(self):
        """The ticks that can be evaluated."""
        return np.flatnonzero(self.status == 0)

    @property
    def applied(self):
        """Per tick, whether the module's inputs were set before the tick ended."""
        return (self.status == 0) | np.isin(self.status, self.late)

    def stream_error(self, tick):
        """Return the error the ``Stream`` constructor raises for the invalid inlet of a tick."""
        port = self.ports[-self.status[tick] - 1]
        values = {
            name: float(self.fields[port, name][tick])
            for name in STREAM_FIELDS
            if (port, name) in self.fields
        }
        try:
            Stream._si(**values, fluid=self.fluids[port])
        except Exception as error:
            return error


def read(twin, aligned, start, stop):
    """Return the ``Block`` of ``twin`` over the ticks ``[start, stop)`` of ``aligned`` samples."""
    block = Block(stop - start, np.zeros(stop - start, dtype=int), [], twin.ports)
    defaults = {port: _defaults(twin, port) for port in twin.ports}
    for source in twin.sources:
        if source.kind == "stream":
            _check_stream(block, twin, source.key, defaults[source.key])
            continue
        column = source.binding.column
        values = units.array_to_si(
            aligned.numbers(column)[start:stop], source.binding.unit, source.quantity
        )
        _mark_missing(block, source, aligned.present(column)[start:stop])
        if source.density is not None:
            module = source.density
            values = mass_flow(values, module.fluid, module.pressure, module.temperature)
        _store(block, source, values)
    return block


def _defaults(twin, port):
    """Return the default stream fields of an inlet as floats."""
    fields = twin.defaults.get(port, {})
    return {name: float(value) for name, value in fields.items() if name != "fluid"}


def _mark_missing(block, source, present):
    """Give the ticks that miss this source, and nothing before, a skip status."""
    missing = (block.status == 0) & ~present
    if not missing.any():
        return
    block.reasons.append(source.binding.column)
    block.status[missing] = len(block.reasons)
    if source.kind == "state":
        block.late += (len(block.reasons),)


def _store(block, source, values):
    target = {
        "input": block.inputs,
        "field": block.fields,
        "measured": block.measured,
        "state": block.states,
    }[source.kind]
    target[source.key] = values


def _check_stream(block, twin, port, defaults):
    """Complete the fields of an inlet from its defaults and mark the ticks it refuses."""
    for name, value in defaults.items():
        block.fields.setdefault((port, name), np.full(block.size, value))
    fluid = twin.defaults.get(port, {}).get("fluid", twin.module.fluid)
    block.fluids[port] = Fluid._of(fluid)
    present = [(port, name) in block.fields for name in STREAM_FIELDS]
    if not all(present):
        block.status[block.status == 0] = -(block.ports.index(port) + 1)
        return
    m_dot, temperature, pressure = (block.fields[port, name] for name in STREAM_FIELDS)
    if _volumetric(twin, port):
        block.fields[port, "m_dot"] = m_dot = mass_flow(
            m_dot, block.fluids[port], pressure, temperature
        )
    with np.errstate(all="ignore"):
        valid = stream_valid(m_dot, temperature, pressure)
    refused = (block.status == 0) & ~np.broadcast_to(valid, (block.size,))
    block.status[refused] = -(block.ports.index(port) + 1)


def _volumetric(twin, port):
    """Whether the inlet's mass flow is bound to a volumetric flow column."""
    return any(
        source.kind == "field"
        and source.key == (port, "m_dot")
        and source.binding.unit in VOLUMETRIC_UNITS
        for source in twin.sources
    )
