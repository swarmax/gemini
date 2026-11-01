"""Immutable fluid streams exchanged by equipment ports."""

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from gemini import ops, units
from gemini._utils.strings import did_you_mean, join_names
from gemini.errors import PhysicsError, ValidationError
from gemini.physics import fluid as fluid_physics
from gemini.types.fluid import Fluid
from gemini.types.quantities import MassFlow, Pressure, Temperature

_ARGUMENTS = ("m_dot", "flow", "T", "p", "fluid")
STREAM_FIELDS = ("m_dot", "T", "p")
"""The numeric fields of a stream, in order; every other list of them is derived from this."""
FIELD_QUANTITIES = {"m_dot": "mass_flow", "T": "temperature", "p": "pressure"}
"""The port quantity of ``Results`` that shows each field of a stream."""

_FIELDS = (*STREAM_FIELDS, "fluid")


@dataclass(frozen=True, slots=True, init=False)
class Stream:
    """Fluid stream passed between component ports (SI units).

    ``m_dot`` is the mass flow, negative for reverse flow [kg/s]; ``T`` the temperature [K];
    ``p`` the absolute pressure [Pa]; ``fluid`` the immutable composition and property model.
    The constructor is keyword-only and validates at the boundary: numbers become ``float``,
    ``m_dot`` must be finite, ``T`` positive and finite, ``p`` non-negative and finite
    (``PhysicsError``). The same class carries arrays over time and traced values on the
    batched and traced paths; the limits are then ``gemini.ops.check`` calls.
    """

    m_dot: MassFlow
    T: Temperature
    p: Pressure
    fluid: Fluid

    def __init__(self, **data):
        """Accept convenient public units while retaining SI fields.

        ``flow`` accepts mass flow, or volume flow converted with the stream's fluid density;
        plain numbers are kg/s. ``fluid`` defaults to the runtime default fluid.
        ``gemini.runtime`` is imported here because it imports ``gemini.types.fluid``;
        a module-level import would form an import cycle through ``gemini.types``.
        """
        from gemini import runtime

        _check_arguments(data)
        fluid = runtime.get_default_fluid() if data.get("fluid") is None else data["fluid"]
        fluid = _as_fluid(fluid)
        temperature = units.value_in_si(data["T"], "K", "Stream.T")
        pressure = units.value_in_si(data["p"], "Pa", "Stream.p")
        if "m_dot" in data:
            mass_flow = units.value_in_si(data["m_dot"], "kg/s", "Stream.m_dot")
        else:
            mass_flow = _mass_flow(data["flow"], fluid, pressure, temperature)
        values = _validated(m_dot=mass_flow, T=temperature, p=pressure)
        for name in STREAM_FIELDS:
            object.__setattr__(self, name, values[name])
        object.__setattr__(self, "fluid", fluid)

    def __str__(self):
        """Return the fields as ``name=value`` pairs."""
        m_dot, T, p = (_shown(getattr(self, name)) for name in STREAM_FIELDS)
        return f"m_dot={m_dot!r} T={T!r} p={p!r} fluid={self.fluid!r}"

    def _numpy(self):
        """Return this stream with exact-float fields as ``np.float64``, itself without any.

        The eager scope gives a module's ``forward`` such a copy, so arithmetic on stream fields
        is silent on a zero divisor; arrays and traced fields stay as they are.
        """
        m_dot, temperature, pressure = self.m_dot, self.T, self.p
        if (
            type(m_dot) is not float
            and type(temperature) is not float
            and type(pressure) is not float
        ):
            return self
        return type(self)._trusted(
            ops.scope.wrap(m_dot), ops.scope.wrap(temperature), ops.scope.wrap(pressure), self.fluid
        )

    def _plain(self):
        """Return this stream with plain Python scalar fields, raising the error of a ``Failed``.

        Returns the stream itself when nothing needs converting.
        """
        fields = [getattr(self, name) for name in STREAM_FIELDS]
        converted = [ops.scope.plain(value) for value in fields]
        if all(new is old for new, old in zip(converted, fields)):
            return self
        return type(self)._trusted(*converted, self.fluid)

    def volumetric_flow(self):
        """Return signed mixture volume flow [m3/s] using the stream fluid."""
        return fluid_physics.volume_flow(self.m_dot, self.fluid.density_at(self.p, self.T))

    def heat_capacity_rate(self):
        """Return the signed heat capacity rate ``m_dot * cp_l`` [W/K] of the stream."""
        return fluid_physics.heat_capacity_rate(
            self.m_dot, self.fluid.properties(self.p, self.T).cp_l
        )

    def quantities(self):
        """Return the quantities of this stream as a port shows them (``stream_quantities``)."""
        fluid = self.fluid
        properties = fluid.properties(self.p, self.T)
        return fluid_physics.stream_quantities(
            self.m_dot,
            self.T,
            self.p,
            fluid.density_at(self.p, self.T),
            properties.cp_l,
            fluid.gas_share(),
            fluid.co2_in_gas(),
            fluid.heating_value(),
        )

    def with_(self, **changes) -> "Stream":
        """Return a copy with updated SI stream fields.

        The copy skips the constructor: it reuses the same ``Fluid`` and checks only the changed
        fields against the physical limits, which raise ``PhysicsError`` (``analysis.solves``
        relies on it to bracket a solver). Values may be floats, arrays or traced values.
        """
        unknown = [name for name in changes if name not in _FIELDS]
        if unknown:
            raise ValidationError(
                f"Stream.with_: unknown field {unknown[0]!r}; valid names: "
                f"{join_names(_FIELDS)}{did_you_mean(unknown[0], _FIELDS)}",
                code="invalid_call",
            )
        if "fluid" in changes:
            changes["fluid"] = _as_fluid(changes["fluid"])
        changes |= _validated(**{name: value for name, value in changes.items() if name != "fluid"})
        return type(self)._trusted(**({name: getattr(self, name) for name in _FIELDS} | changes))

    @classmethod
    def _trusted(cls, m_dot, T, p, fluid):
        """Return a stream of already validated values without running the constructor.

        The tracer builds its inlet streams with it, so a trace records no limit checks for
        values the caller validated; ``with_`` builds its copies with it.
        """
        stream = object.__new__(cls)
        object.__setattr__(stream, "m_dot", m_dot)
        object.__setattr__(stream, "T", T)
        object.__setattr__(stream, "p", p)
        object.__setattr__(stream, "fluid", fluid)
        return stream


def _shown(value):
    """Return an ``np.float64`` as a ``float``, so ``repr`` shows the number alone."""
    return float(value) if type(value) is np.float64 else value


def _check_arguments(data):
    """Reject unknown, conflicting and missing constructor keywords with ``ValidationError``."""
    for name in data:
        if name not in _ARGUMENTS:
            raise ValidationError(
                f"Stream: unknown argument {name!r}; valid names: "
                f"{join_names(_ARGUMENTS)}{did_you_mean(name, _ARGUMENTS)}",
                code="invalid_call",
            )
    if "flow" in data and "m_dot" in data:
        raise ValidationError("Stream: pass either flow or m_dot, not both", code="invalid_call")
    required = ("T", "p") if "flow" in data or "m_dot" in data else ("m_dot", "T", "p")
    missing = [name for name in required if name not in data]
    if missing:
        raise ValidationError(f"Stream: missing argument {', '.join(missing)}", code="invalid_call")


def _as_fluid(value):
    """Return ``value`` as a ``Fluid``: an instance, or a mapping of its fields."""
    if isinstance(value, Fluid):
        return value
    if isinstance(value, Mapping):
        return Fluid.model_validate(value)
    raise ValidationError(
        f"Stream.fluid: value = {value!r}; expected a Fluid or a mapping of its fields",
        code="invalid_call",
    )


def _number(name, value):
    """Return ``value`` as a ``float``; arrays and traced values pass unchanged."""
    if isinstance(value, (np.ndarray, ops.Symbolic)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise PhysicsError(f"Stream.{name}: value = {value!r}; expected a number") from error


def _validated(**values):
    """Return the given ``m_dot``, ``T`` and ``p`` as floats, arrays or traced values, checked.

    ``m_dot`` must be finite, ``T`` positive and finite, ``p`` non-negative and finite. The
    limits are ``ops.check`` calls on ``&`` of two comparisons, so one rule serves floats, arrays
    and traced values.
    """
    values = {name: _number(name, value) for name, value in values.items()}
    for name, value in values.items():
        ops.check(
            _within(name, value),
            PhysicsError,
            "Stream: {name} = {value} {unit}; expected {expected}",
            name=name,
            value=value,
            unit=_LIMITS[name][2],
            expected=_EXPECTED[name],
        )
    return values


def _within(name, value):
    """Return whether ``value`` satisfies the limit of stream field ``name``; any array shape."""
    lower, strict, _ = _LIMITS[name]
    above = value > lower if strict else value >= lower
    return above & (value < math.inf)


def stream_valid(m_dot, T, p):
    """Return, per row, whether ``Stream(m_dot, T, p)`` accepts the values: the limits' one rule."""
    return _within("m_dot", m_dot) & _within("T", T) & _within("p", p)


_LIMITS = {"m_dot": (-math.inf, True, "kg/s"), "T": (0, True, "K"), "p": (0, False, "Pa")}
_EXPECTED = {"m_dot": "a finite mass flow", "T": "T > 0 and finite", "p": "p >= 0 and finite"}


def mass_flow(volume_flow, fluid, pressure, temperature):
    """Return a volume flow [m3/s] as mass flow [kg/s] with the density of ``fluid`` at (p, T)."""
    return volume_flow * fluid.density_at(pressure, temperature)


def _mass_flow(flow, fluid, pressure, temperature):
    """Return a public ``flow`` value as mass flow [kg/s], using density for volume units."""
    if isinstance(flow, Mapping):
        flow = units.Quantity.from_dict(flow)
    if isinstance(flow, units.Quantity) and units.si_unit(flow.unit) == "m3/s":
        volume = units.value_in_si(flow, "m3/s", "Stream.flow")
        return mass_flow(volume, fluid, pressure, temperature)
    return units.value_in_si(flow, "kg/s", "Stream.flow")
