"""Unit conversions at package and correlation boundaries; historical factors retained.

The ``*_to_*`` functions convert at correlation boundaries that use US or laboratory units.
``_UNITS`` is the single table of public data units: every unit maps to its SI unit, a scale
and an offset, ``si = value * scale + offset``. ``Unit``, the enum of the units, is generated from
it, and ``to_si``, ``convert``, ``value_in_si``, ``si_unit``, ``names``, ``fits`` and the unit sets
of ``Profile`` and ``Stream`` all read it. ``define_quantity`` records the SI unit of each named
quantity (the types package calls it once per quantity), so ``names(quantity)`` and
``fits(unit, quantity)`` need no upward import.

Each conversion factor is declared once, as a named module constant below, and both the table
and the converters read that constant.

Validity: every converter is valid for any finite number; the argument is returned scaled (and
offset for temperatures), with no range check. Source: NIST Special Publication 811 (2008) for
the exact definitions (bar, inch, foot, psi, hour, degree Celsius). Where a value is a retained
number of the original GEMINI (the millidarcy, barrel per day, foot of head, brake horsepower,
lbm/ft3 and psi factors), that historical factor is kept bit for bit, whatever its digits.

The converters are not decorated with ``@ops.physics``: they sit on the hot path of every
binding and plain operators work on every backend, so the registry wrapper would only add cost.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from gemini._utils.strings import close_matches, did_you_mean, join_names
from gemini.errors import ValidationError

KILO = 1000
MEGA = 1e6
GIGA = 1e9
MILLI = 1e-3
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 24 * SECONDS_PER_HOUR
SECONDS_PER_YEAR = 365.25 * SECONDS_PER_DAY
ZERO_CELSIUS = 273.15
"""Temperature [K] of 0 degC."""
PA_PER_BAR = 1e5
PA_PER_KPA = 1e3
STANDARD_ATMOSPHERE = 101325
"""Standard atmosphere [Pa], the offset of gauge pressure."""
JOULES_PER_KWH = 3.6e6
M_PER_INCH = 0.0254
M_PER_FOOT = 0.3048
FAHRENHEIT_PER_KELVIN = 1.8
FAHRENHEIT_OFFSET = 32
PSI_PER_BAR = 14.503774
M2_PER_MILLIDARCY = 9.869233e-16
BBL_PER_DAY_PER_M3S = 543439.650564
PA_PER_FOOT_HEAD = 2988.30167
W_PER_BHP = 745.7
KGM3_PER_LBMFT3 = 1.601846e1
HALF_TURN_DEGREES = 180
MOL_M3_PA_PER_MOL_L_BAR = 0.01
API_VELOCITY_FACTOR = 0.3048 / math.sqrt(0.0283 / 0.454)

__all__ = ["Quantity", "Unit", "names", "convert", "fits"]


def bar_to_pa(x: float) -> float:
    """Convert [bar] to [Pa]: ``x * 1e5``."""
    return x * PA_PER_BAR


def pa_to_bar(x: float) -> float:
    """Convert [Pa] to [bar]: ``x / 1e5``."""
    return x / PA_PER_BAR


def c_to_k(x: float) -> float:
    """Convert [degC] to [K]: ``x + 273.15``."""
    return x + ZERO_CELSIUS


def k_to_c(x: float) -> float:
    """Convert [K] to [degC]: ``x - 273.15``."""
    return x - ZERO_CELSIUS


def m3h_to_m3s(x: float) -> float:
    """Convert [m3/h] to [m3/s]: ``x / 3600``."""
    return x / SECONDS_PER_HOUR


def m3s_to_m3h(x: float) -> float:
    """Convert [m3/s] to [m3/h]: ``x * 3600``."""
    return x * SECONDS_PER_HOUR


def md_to_m2(x: float) -> float:
    """Convert [mD] to [m2]: ``x * 9.869233e-16``."""
    return x * M2_PER_MILLIDARCY


def m2_to_md(x: float) -> float:
    """Convert [m2] to [mD]: ``x / 9.869233e-16``."""
    return x / M2_PER_MILLIDARCY


def m3s_to_bbl_per_day(x: float) -> float:
    """Convert [m3/s] to [bbl/day]: ``x * 543439.650564``."""
    return x * BBL_PER_DAY_PER_M3S


def bbl_per_day_to_m3s(x: float) -> float:
    """Convert [bbl/day] to [m3/s]: ``x / 543439.650564``."""
    return x / BBL_PER_DAY_PER_M3S


def ft_head_to_pa(x: float) -> float:
    """Convert [ft head] to [Pa]: ``x * 2988.30167``."""
    return x * PA_PER_FOOT_HEAD


def pa_to_ft_head(x: float) -> float:
    """Convert [Pa] to [ft head]: ``x / 2988.30167``."""
    return x / PA_PER_FOOT_HEAD


def bhp_to_w(x: float) -> float:
    """Convert [bhp] to [W]: ``x * 745.7``."""
    return x * W_PER_BHP


def w_to_bhp(x: float) -> float:
    """Convert [W] to [bhp]: ``x / 745.7``."""
    return x / W_PER_BHP


def m_to_ft(x: float) -> float:
    """Convert [m] to [ft]: ``x / 0.3048``."""
    return x / M_PER_FOOT


def ft_to_m(x: float) -> float:
    """Convert [ft] to [m]: ``x * 0.3048``."""
    return x * M_PER_FOOT


def kgm3_to_lbmft3(x: float) -> float:
    """Convert [kg/m3] to [lbm/ft3]: ``x / 16.01846``."""
    return x / KGM3_PER_LBMFT3


def lbmft3_to_kgm3(x: float) -> float:
    """Convert [lbm/ft3] to [kg/m3]: ``x * 16.01846``."""
    return x * KGM3_PER_LBMFT3


def pas_to_cp(x: float) -> float:
    """Convert [Pa s] to [cP]: ``x / 1e-3``."""
    return x / MILLI


def cp_to_pas(x: float) -> float:
    """Convert [cP] to [Pa s]: ``x * 1e-3``."""
    return x * MILLI


def inch_to_m(x: float) -> float:
    """Convert [inch] to [m]: ``x * 0.0254``."""
    return x * M_PER_INCH


def m_to_mm(x: float) -> float:
    """Convert [m] to [mm]: ``x * 1000``."""
    return x * KILO


def m3s_to_m3day(x: float) -> float:
    """Convert [m3/s] to [m3/day]: ``x * 86400``."""
    return x * SECONDS_PER_DAY


def m3day_to_m3s(x: float) -> float:
    """Convert [m3/day] to [m3/s]: ``x / 86400``."""
    return x / SECONDS_PER_DAY


def index_to_si(x: float) -> float:
    """Convert [m3/h/bar] to [m3/s/Pa]: ``x / 3600 / 1e5``."""
    return x / SECONDS_PER_HOUR / PA_PER_BAR


def index_from_si(x: float) -> float:
    """Convert [m3/s/Pa] to [m3/h/bar]: ``x * 3600 * 1e5``."""
    return x * SECONDS_PER_HOUR * PA_PER_BAR


def c_to_f(x: float) -> float:
    """Convert [degC] to [degF]: ``x * 1.8 + 32``."""
    return x * FAHRENHEIT_PER_KELVIN + FAHRENHEIT_OFFSET


def bar_to_psi(x: float) -> float:
    """Convert [bar] to [psi]: ``x * 14.503774``."""
    return x * PSI_PER_BAR


def pa_to_gpa(x: float) -> float:
    """Convert [Pa] to [GPa]: ``x / 1e9``."""
    return x / GIGA


def rad_to_deg(x: float) -> float:
    """Convert [rad] to [deg]: ``x * 180 / pi``."""
    return x * HALF_TURN_DEGREES / math.pi


def deg_to_rad(x: float) -> float:
    """Convert [deg] to [rad]: ``x * pi / 180``."""
    return x * math.pi / HALF_TURN_DEGREES


def m2_to_mm2(x: float) -> float:
    """Convert [m2] to [mm2]: ``x * 1e6``."""
    return x * MEGA


def ms_to_mm_year(x: float) -> float:
    """Convert penetration speed [m/s] to [mm/year]: ``x * 1000 * 31557600``."""
    return x * KILO * SECONDS_PER_YEAR


def mol_l_bar_to_mol_m3_pa(x: float) -> float:
    """Convert Henry solubility constant [mol/l/bar] to [mol/m3/Pa]: ``x * 0.01``."""
    return x * MOL_M3_PA_PER_MOL_L_BAR


_UNITS = {
    "Pa": ("Pa", 1, 0),
    "bar": ("Pa", PA_PER_BAR, 0),
    "barg": ("Pa", PA_PER_BAR, STANDARD_ATMOSPHERE),
    "bar(g)": ("Pa", PA_PER_BAR, STANDARD_ATMOSPHERE),
    "kPa": ("Pa", PA_PER_KPA, 0),
    "MPa": ("Pa", MEGA, 0),
    "K": ("K", 1, 0),
    "degC": ("K", 1, ZERO_CELSIUS),
    "C": ("K", 1, ZERO_CELSIUS),
    "°C": ("K", 1, ZERO_CELSIUS),
    "m3/s": ("m3/s", 1, 0),
    "m3/h": ("m3/s", 1 / SECONDS_PER_HOUR, 0),
    "l/s": ("m3/s", MILLI, 0),
    "kg/s": ("kg/s", 1, 0),
    "t/h": ("kg/s", KILO / SECONDS_PER_HOUR, 0),
    "Hz": ("Hz", 1, 0),
    "rpm": ("Hz", 1 / SECONDS_PER_MINUTE, 0),
    "W": ("W", 1, 0),
    "kW": ("W", KILO, 0),
    "MW": ("W", MEGA, 0),
    "GW": ("W", GIGA, 0),
    "J": ("J", 1, 0),
    "kWh": ("J", JOULES_PER_KWH, 0),
    "MWh": ("J", KILO * JOULES_PER_KWH, 0),
    "GWh": ("J", MEGA * JOULES_PER_KWH, 0),
    "TWh": ("J", GIGA * JOULES_PER_KWH, 0),
    "MJ": ("J", MEGA, 0),
    "GJ": ("J", GIGA, 0),
    "currency": ("currency", 1, 0),
    "currency/yr": ("currency/yr", 1, 0),
    "currency/J": ("currency/J", 1, 0),
    "currency/kWh": ("currency/J", 1 / JOULES_PER_KWH, 0),
    "currency/MWh": ("currency/J", 1 / (KILO * JOULES_PER_KWH), 0),
    "currency/kg": ("currency/kg", 1, 0),
    "currency/t": ("currency/kg", 1 / KILO, 0),
    "currency/s": ("currency/s", 1, 0),
    "currency/h": ("currency/s", 1 / SECONDS_PER_HOUR, 0),
    "currency/W": ("currency/W", 1, 0),
    "currency/m": ("currency/m", 1, 0),
    "currency/(W/K)": ("currency/(W/K)", 1, 0),
    "currency/m3": ("currency/m3", 1, 0),
    "EUR": ("currency", 1, 0),
    "kEUR": ("currency", KILO, 0),
    "MEUR": ("currency", MEGA, 0),
    "EUR/J": ("currency/J", 1, 0),
    "EUR/yr": ("currency/yr", 1, 0),
    "kEUR/yr": ("currency/yr", KILO, 0),
    "MEUR/yr": ("currency/yr", MEGA, 0),
    "EUR/MWh": ("currency/J", 1 / (KILO * JOULES_PER_KWH), 0),
    "EUR/kWh": ("currency/J", 1 / JOULES_PER_KWH, 0),
    "EUR/kg": ("currency/kg", 1, 0),
    "EUR/t": ("currency/kg", 1 / KILO, 0),
    "EUR/W": ("currency/W", 1, 0),
    "EUR/m": ("currency/m", 1, 0),
    "EUR/(W/K)": ("currency/(W/K)", 1, 0),
    "EUR/m3": ("currency/m3", 1, 0),
    "m": ("m", 1, 0),
    "km": ("m", KILO, 0),
    "mm": ("m", MILLI, 0),
    "in": ("m", M_PER_INCH, 0),
    "ft": ("m", M_PER_FOOT, 0),
    "s": ("s", 1, 0),
    "min": ("s", SECONDS_PER_MINUTE, 0),
    "h": ("s", SECONDS_PER_HOUR, 0),
    "d": ("s", SECONDS_PER_DAY, 0),
    "yr": ("s", SECONDS_PER_YEAR, 0),
    "m/s": ("m/s", 1, 0),
    "m2": ("m2", 1, 0),
    "mD": ("m2", md_to_m2(1), 0),
    "m3": ("m3", 1, 0),
    "rad": ("rad", 1, 0),
    "kg/m3": ("kg/m3", 1, 0),
    "g/m3": ("kg/m3", MILLI, 0),
    "mg/l": ("kg/m3", MILLI, 0),
    "Pa.s": ("Pa.s", 1, 0),
    "mPa.s": ("Pa.s", MILLI, 0),
    "mPa*s": ("Pa.s", MILLI, 0),
    "J/kg/K": ("J/kg/K", 1, 0),
    "J/kg": ("J/kg", 1, 0),
    "kJ/kg": ("J/kg", KILO, 0),
    "J/K": ("J/K", 1, 0),
    "kWh/K": ("J/K", JOULES_PER_KWH, 0),
    "J/m3/K": ("J/m3/K", 1, 0),
    "MJ/m3/K": ("J/m3/K", MEGA, 0),
    "m2/s": ("m2/s", 1, 0),
    "W/m": ("W/m", 1, 0),
    "m.K/W": ("m.K/W", 1, 0),
    "K/m": ("K/m", 1, 0),
    "K/km": ("K/m", MILLI, 0),
    "kg": ("kg", 1, 0),
    "t": ("kg", KILO, 0),
    "kt": ("kg", MEGA, 0),
    "Mt": ("kg", GIGA, 0),
    "kg/yr": ("kg/yr", 1, 0),
    "t/yr": ("kg/yr", KILO, 0),
    "kt/yr": ("kg/yr", MEGA, 0),
    "Mt/yr": ("kg/yr", GIGA, 0),
    "J/yr": ("J/yr", 1, 0),
    "kWh/yr": ("J/yr", JOULES_PER_KWH, 0),
    "MWh/yr": ("J/yr", KILO * JOULES_PER_KWH, 0),
    "GWh/yr": ("J/yr", MEGA * JOULES_PER_KWH, 0),
    "1/yr": ("1/yr", 1, 0),
    "%/yr": ("1/yr", 0.01, 0),
    "kg/J": ("kg/J", 1, 0),
    "g/kWh": ("kg/J", MILLI / JOULES_PER_KWH, 0),
    "m3/s/Pa^0.5": ("m3/s/Pa^0.5", 1, 0),
    "m3/h/bar^0.5": ("m3/s/Pa^0.5", 1 / SECONDS_PER_HOUR / PA_PER_BAR**0.5, 0),
    "W/m/K": ("W/m/K", 1, 0),
    "W/m2/K": ("W/m2/K", 1, 0),
    "W/K": ("W/K", 1, 0),
    "m3/s/Pa": ("m3/s/Pa", 1, 0),
    "m3/h/bar": ("m3/s/Pa", 1 / SECONDS_PER_HOUR / PA_PER_BAR, 0),
    "-": ("-", 1, 0),
    "ppm": ("-", 1e-6, 0),
    "Nm3/m3": ("-", 1, 0),
}

_QUANTITY_UNITS = {}

QUANTITY_FORM = (
    "a Quantity or {'value': <number>, 'unit': <unit>}, e.g. {'value': 150, 'unit': 'm3/h'}"
)
"""How a value with a dimension is written; the message of every refused text shows it."""

_NAMED = {
    "-": "DIMENSIONLESS",
    "degC": "DEG_C",
    "°C": "DEGREE_C",
    "bar(g)": "BAR_G",
    "mPa*s": "MPA_TIMES_S",
    "1/yr": "PER_YR",
}
_SPELLED = (
    ("%", "PERCENT"),
    ("(", ""),
    (")", ""),
    ("/", "_PER_"),
    (".", "_"),
    ("^", "_"),
)


def _member_name(unit):
    """Return the member name of ``unit``: upper case words, ``/`` read as ``_PER_``."""
    if unit in _NAMED:
        return _NAMED[unit]
    name = unit
    for old, new in _SPELLED:
        name = name.replace(old, new)
    return name.upper()


Unit = StrEnum("Unit", {_member_name(unit): unit for unit in _UNITS})
Unit.__doc__ = (
    "The units of the unit table, as strings: ``Unit.M3_PER_H == 'm3/h'``. Generated from the "
    "table, so a unit has one source; ``Quantity`` and every dimensioned input take a member."
)


def _unit(unit, path="units"):
    """Return the ``Unit`` member of a known unit string, or raise ``invalid_unit``."""
    if unit not in _UNITS:
        raise ValidationError(
            f"{path}: unit = {unit!r}; expected a known unit{did_you_mean(unit, _UNITS)}",
            code="invalid_unit",
        )
    return Unit(unit)


@dataclass(frozen=True, eq=False)
class Quantity:
    """A number or array with its unit: the one shape of a value with a dimension.

    ``unit`` is a ``Unit``; a known unit string is turned into the member. ``si`` is the value in
    SI, ``to`` a new quantity in another unit of the same dimension, ``to_dict`` the JSON form
    ``{"value": ..., "unit": ...}``. Two quantities are equal when their SI values are.
    """

    value: float
    unit: Unit

    def __post_init__(self):
        """Turn the unit into its ``Unit`` member and a list of numbers into an array."""
        object.__setattr__(self, "unit", _unit(self.unit, "Quantity"))
        if isinstance(self.value, (list, tuple)):
            object.__setattr__(self, "value", np.asarray(self.value, dtype=float))

    @property
    def si(self):
        """The value in SI (a float, or an array for an array value)."""
        if isinstance(self.value, np.ndarray):
            return array_to_si(self.value, self.unit)
        return to_si(self.value, self.unit)

    def to(self, unit, quantity=None):
        """Return the quantity in ``unit``.

        ``quantity`` names a difference such as ``"temperature_difference"``, which converts by
        scale only.
        """
        unit = _unit(unit, "Quantity.to")
        if isinstance(self.value, np.ndarray):
            return Quantity(array_convert(self.value, self.unit, unit, quantity), unit)
        return Quantity(convert(self.value, self.unit, unit, quantity), unit)

    def to_dict(self):
        """Return ``{"value": ..., "unit": ...}`` as plain data."""
        value = self.value.tolist() if isinstance(self.value, np.ndarray) else self.value
        return {"value": value, "unit": str(self.unit)}

    @classmethod
    def from_dict(cls, data):
        """Return the quantity of ``{"value": ..., "unit": ...}``; any other shape raises."""
        if not isinstance(data, Mapping) or set(data) != {"value", "unit"}:
            raise ValidationError(
                f"quantity = {data!r}; expected {QUANTITY_FORM}",
                code="invalid_value",
            )
        value = data["value"]
        return cls(
            np.asarray(value, dtype=float) if isinstance(value, list) else value, data["unit"]
        )

    def __eq__(self, other):
        """Compare SI values."""
        if not isinstance(other, Quantity):
            return NotImplemented
        return bool(np.array_equal(self.si, other.si))

    def __hash__(self):
        """Hash the SI value of a scalar."""
        return hash(float(self.si))


def _entry(unit, path="units"):
    """Return ``(si_unit, scale, offset)`` of a known unit."""
    if unit not in _UNITS:
        raise ValidationError(
            f"{path}: unit = {unit!r}; expected a known unit{did_you_mean(unit, _UNITS)}",
            code="invalid_unit",
        )
    return _UNITS[unit]


def _offset(unit, quantity):
    """Return the offset of ``unit``, or zero for a ``*_difference`` quantity.

    A difference of 10 degC is a difference of 10 K, and a pressure difference in barg equals
    the same difference in bar, so differences convert by scale only.
    """
    if quantity is not None and quantity.endswith("_difference"):
        return 0
    return _UNITS[unit][2]


def si_unit(unit):
    """Return the SI unit that ``unit`` converts to, or ``None`` for an unknown unit."""
    entry = _UNITS.get(unit)
    return entry[0] if entry else None


def si_conversion(unit, quantity=None):
    """Return ``(scale, offset)`` with ``to_si(value) == float(value) * scale + offset``.

    Array code converts a whole column with the same two numbers, which gives the bits of the
    scalar conversion row by row.
    """
    _, scale, _ = _entry(unit, "units.si_conversion")
    return scale, _offset(unit, quantity)


def to_si(value: float, unit: str, quantity: str | None = None) -> float:
    """Convert a bound scalar to SI; volume flow remains [m3/s] until density is known."""
    scale, offset = si_conversion(unit, quantity)
    return float(value) * scale + offset


def array_to_si(values, unit, quantity=None):
    """Convert an array-like of ``unit`` values to SI, element for element as ``to_si`` does."""
    scale, offset = si_conversion(unit, quantity)
    return np.asarray(values, dtype=float) * scale + offset


def array_convert(values, from_unit, to_unit, quantity=None):
    """Convert an array-like between units of one dimension, element for element as ``convert``."""
    target = _same_dimension(from_unit, to_unit)
    si = array_to_si(values, from_unit, quantity)
    return (si - _offset(to_unit, quantity)) / target[1]


def _same_dimension(from_unit, to_unit):
    """Return the table entry of ``to_unit``; a unit of another dimension raises."""
    source, target = _entry(from_unit, "units.convert"), _entry(to_unit, "units.convert")
    if source[0] != target[0]:
        raise ValidationError(
            f"units.convert: unit = {to_unit!r}; expected a unit of {source[0]!r} "
            f"to convert from {from_unit!r}",
            code="invalid_unit",
        )
    return target


def _allowed(expected_unit, quantity):
    """Return the units a field of SI unit ``expected_unit`` accepts."""
    if quantity is not None:
        return names(quantity)
    return sorted(unit for unit, entry in _UNITS.items() if entry[0] == expected_unit)


def _as_quantity(value, expected_unit, path):
    """Return ``value`` as a ``Quantity`` if it is one or its dict, ``None`` if it is a plain value.

    Text for a field with a unit is refused: a value with a dimension is written as a ``Quantity``
    or its dict.
    """
    if isinstance(value, Quantity):
        return value
    if isinstance(value, str) and expected_unit is not None:
        raise ValidationError(
            f"{path}: value = {value!r}; expected {QUANTITY_FORM}", code="invalid_value"
        )
    if isinstance(value, Mapping) and expected_unit is not None:
        try:
            return Quantity.from_dict(value)
        except ValidationError as error:
            raise ValidationError(f"{path}: {error}", code=error.code) from error
    return None


def value_in_si(value, expected_unit=None, path="value", quantity=None):
    """Convert a ``Quantity`` or its dict to a declaration's SI unit.

    A plain number is SI already and passes unchanged, as does every value of a declaration
    without a unit. A text for a declaration with a unit raises ``invalid_value``. ``quantity``
    names the declared quantity so that differences ignore unit offsets; a unit of another
    dimension raises ``invalid_unit`` listing the units of the field.
    """
    given = _as_quantity(value, expected_unit, path)
    if given is None or expected_unit is None:
        return value
    if _entry(given.unit, path)[0] != expected_unit:
        allowed = _allowed(expected_unit, quantity)
        raise ValidationError(
            f"{path}: unit = {str(given.unit)!r}; expected one of {join_names(allowed)}",
            code="invalid_unit",
        )
    if isinstance(given.value, np.ndarray):
        scale, offset = si_conversion(given.unit, quantity)
        return given.value * scale + offset
    return to_si(given.value, given.unit, quantity)


def convert(value, from_unit, to_unit, quantity=None):
    """Convert a scalar between units of the same dimension through SI.

    A unit converts to itself even when it is not in the unit table. ``quantity`` names the
    declared quantity so that differences ignore unit offsets.
    """
    if from_unit == to_unit and from_unit not in _UNITS:
        return value
    target = _same_dimension(from_unit, to_unit)
    si = to_si(value, from_unit, quantity)
    return (si - _offset(to_unit, quantity)) / target[1]


def define_quantity(name, unit):
    """Record that the quantity ``name`` is stored in the SI unit ``unit``.

    Defining a name again with the same unit changes nothing; another unit raises
    ``ValidationError``.
    """
    known = _QUANTITY_UNITS.setdefault(name, unit)
    if known != unit:
        raise ValidationError(
            f"units.define_quantity: quantity {name!r} = {unit!r}; already {known!r}",
            code="invalid_unit",
        )


def _quantity_si_unit(quantity):
    """Return the SI unit of a named quantity, or raise with the closest names."""
    if quantity not in _QUANTITY_UNITS:
        raise ValidationError(
            f"units: quantity = {quantity!r}; expected one of "
            f"{join_names(sorted(_QUANTITY_UNITS))}{did_you_mean(quantity, _QUANTITY_UNITS)}",
            suggestions=close_matches(quantity, _QUANTITY_UNITS),
            code="unknown_name",
        )
    return _QUANTITY_UNITS[quantity]


def family(quantity):
    """Return the first quantity defined with the SI unit of ``quantity``, the head of its family.

    ``power`` for ``duty`` or ``electricity``, ``pressure`` for ``pressure_difference``,
    ``temperature`` for ``temperature_difference`` and ``length`` for ``elevation``.
    """
    target = _quantity_si_unit(quantity)
    return next(name for name, unit in _QUANTITY_UNITS.items() if unit == target)


def names(quantity=None):
    """Return the sorted unit names, or those of one quantity such as ``"pressure"``.

    Every unit name returned converts with ``convert``; an unknown quantity raises
    ``ValidationError`` with the closest names.
    """
    if quantity is None:
        return sorted(_UNITS)
    target = _quantity_si_unit(quantity)
    return sorted(unit for unit, entry in _UNITS.items() if entry[0] == target)


def fits(unit, quantity):
    """Whether ``unit`` is a known unit of the named ``quantity`` (``"pressure"``, ``"power"``).

    An unknown unit does not fit; an unknown quantity raises ``ValidationError``.
    """
    return si_unit(unit) == _quantity_si_unit(quantity)
