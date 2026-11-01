"""The economic assumptions of a problem, each with its source or left for the user."""

from typing import Any

import numpy as np
import pydantic
from pydantic import BaseModel, ConfigDict, Field, field_validator

from gemini import units
from gemini._utils.strings import close_matches, did_you_mean, join_names
from gemini.errors import ValidationError
from gemini.units import Quantity, Unit

CARRIERS = {
    "electricity": "currency/J",
    "gas": "currency/J",
    "heat": "currency/J",
    "cold": "currency/J",
    "waste_disposal": "currency/kg",
    "chemical": "currency/kg",
}
"""What has a price, with the SI unit of the price: energy per J, the rest per kg."""
CO2_UNIT = "currency/kg"
"""The SI unit of ``co2_price``."""
AMOUNTS = {
    "co2_price": CO2_UNIT,
    "electricity_emission_factor": "kg/J",
    "drilling_cost": "currency/m",
    "pump_cost": "currency/W",
    "heat_pump_cost": "currency/W",
    "boiler_cost": "currency/W",
    "chp_cost": "currency/W",
    "chiller_cost": "currency/W",
    "exchanger_cost": "currency/(W/K)",
    "degasser_cost": "currency",
    "flare_cost": "currency",
    "makeup_cost": "currency",
}
"""The fields that hold a ``Quantity``, with the SI unit of each."""
FIELD_CODES = {
    "extra_forbidden": "unknown_name",
    "greater_than_equal": "out_of_bounds",
    "less_than_equal": "out_of_bounds",
}
"""The code of what pydantic refuses; anything else is ``invalid_value``."""

COST_SOURCES = {
    "drilling_cost": "SDE+ 2013 reference case, 2300 m doublet, 5.7 MEUR net drilling (Mijnlieff "
    "et al. 2013, EGC, Geothermal energy and support schemes in the Netherlands, slide 26), over "
    "two wells of 2300 m",
    "degasser_cost": "SDE+ 2013 reference case, 1.0 MEUR reserve for separation of hydrocarbons "
    "per doublet (Mijnlieff et al. 2013, EGC, slide 26)",
    "heat_pump_cost": "Danish Energy Agency, Technology Data for Energy Plants, April 2020, "
    "chapter 40, compression heat pump, excess heat, 10 MW, 2020, 2015 prices",
    "boiler_cost": "Danish Energy Agency, Technology Data for Energy Plants, April 2020, chapter "
    "44, district heating boiler, natural gas, 2020, 2015 prices",
    "chp_cost": "Danish Energy Agency, Technology Data for Energy Plants, April 2020, chapter 06, "
    "spark ignition engine, natural gas, 1-10 MWe, 2020, 2015 prices",
}
"""The source of each cost factor with a default; a factor the user gives is theirs."""


class Assumptions(BaseModel):
    """Discount rate, lifetime, prices and emission factors of one problem.

    Every field is ``None`` until the user gives it, except those below that have a source.
    No price, rate or lifetime has a default, because none is valid everywhere: they depend on
    the country, the year, the contract and the project. A price, a cost factor, the CO2 price
    and the emission factor are a ``gm.units.Quantity`` or its dict
    (``{"value": 100, "unit": "EUR/MWh"}``); a plain number or a text is refused, and a unit of
    another dimension raises ``invalid_unit``. The currency is a label: an amount in ``EUR`` is a
    number of ``currency`` and nothing converts between currencies. Invalid values raise
    ``ValidationError``.

    Defaults with a source:

    - ``methane_gwp`` = 29.8 kg CO2-eq per kg of fossil methane over 100 years: IPCC Sixth
      Assessment Report, Working Group I, chapter 7, table 7.15 (Forster et al. 2021).
    - ``currency`` = ``"EUR"``: a label, the currency of the prices you give and of the
      ``Cost`` default; it is not a price.
    - the cost factors of ``COST_SOURCES``, each with its source there. They are valued in
      ``cost_price_year`` = 2015, the prices of the Danish Energy Agency catalogue.
      NOTE(refactor): the two factors of the SDE+ 2013 reference case are 2013 figures, taken into
      that price year without escalation, because ``total_cost`` adds costs of one price year.

    The other cost factors have no value, because no source was found: ``chiller_cost``,
    ``exchanger_cost``, ``pump_cost``, ``flare_cost`` and ``makeup_cost``. Using one raises
    ``ValidationError`` (code ``missing_assumption``). See ``economics.md``.

    Attributes
    ----------
    currency : str
        Currency of every price and result.
    discount_rate : float or None
        Real discount rate per year [-], for example 0.05.
    lifetime_years : int or None
        Years of operation that the levelised cost and the net present value cover.
    prices : dict
        ``{carrier: price}``, a carrier being a name of ``CARRIERS``. A price is a ``Quantity`` or
        its dict, with an array of values for a profile on the demand index. ``electricity`` is
        what the grid sells, ``gas`` what
        the gas grid sells (co-produced gas costs nothing), ``heat`` and ``cold`` the revenue per
        joule delivered, ``waste_disposal`` the cost of a kilogram at a ``WasteGrid`` and
        ``chemical`` of a kilogram from a ``ChemicalGrid``.
    co2_price : Quantity or None
        Cost of CO2-equivalent emitted, in a unit of currency per mass.
    electricity_emission_factor : Quantity or None
        CO2 emitted per energy of grid electricity drawn, in a unit of mass per energy such as
        ``g/kWh``; it depends on the grid and the year, so there is no default.
    methane_gwp : float
        CO2-equivalent of a kilogram of methane released [-].
    heat_cost_share : float or None
        Share of the plant cost charged to heat when a plant delivers heat and cold [-]; the rest
        is charged to cold. Without it such a plant has no levelised cost.
    cost_price_year : int
        Price year of the cost factors.
    drilling_cost : Quantity or None
        Drilling, currency per length of well.
    pump_cost : Quantity or None
        Production pump, currency per power of shaft power at the nominal flow.
    heat_pump_cost, boiler_cost, chiller_cost : Quantity or None
        Equipment, currency per power of capacity; ``chp_cost`` per electric capacity.
    exchanger_cost : Quantity or None
        Heat exchanger, currency per thermal conductance.
    degasser_cost, flare_cost, makeup_cost : Quantity or None
        Fixed items, an amount of currency.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    currency: str = Field("EUR", min_length=1)
    discount_rate: float | None = Field(None, ge=0)
    lifetime_years: int | None = Field(None, ge=1)
    prices: dict[str, Any] = Field(default_factory=dict)
    co2_price: Any = None
    electricity_emission_factor: Any = None
    methane_gwp: float = Field(29.8, ge=0)
    heat_cost_share: float | None = Field(None, ge=0, le=1)
    cost_price_year: int = Field(2015, ge=1)
    drilling_cost: Any = Quantity(5.7e6 / (2 * 2300), Unit.CURRENCY_PER_M)
    pump_cost: Any = None
    heat_pump_cost: Any = Quantity(0.67, Unit.CURRENCY_PER_W)
    boiler_cost: Any = Quantity(0.06, Unit.CURRENCY_PER_W)
    chp_cost: Any = Quantity(0.95, Unit.CURRENCY_PER_W)
    chiller_cost: Any = None
    exchanger_cost: Any = None
    degasser_cost: Any = Quantity(1.0e6, Unit.CURRENCY)
    flare_cost: Any = None
    makeup_cost: Any = None

    @field_validator("prices", mode="before")
    @classmethod
    def _prices(cls, prices):
        """Return the prices with each value a ``Quantity``."""
        if not isinstance(prices, dict):
            raise ValueError("expected a dict of carrier to price")
        return {carrier: _quantity(price, f"prices.{carrier}") for carrier, price in prices.items()}

    @field_validator(*AMOUNTS, mode="before")
    @classmethod
    def _amount(cls, amount, info):
        """Return an amount as a ``Quantity`` of the dimension of its field, or ``None``."""
        if amount is None:
            return None
        amount = _quantity(amount, info.field_name)
        units.value_in_si(amount, AMOUNTS[info.field_name], info.field_name)
        if np.any(amount.si < 0):
            raise ValueError("expected 0 or more")
        return amount

    def __init__(self, **data):
        """Validate the fields, then the prices; every failure is a ``ValidationError``."""
        try:
            super().__init__(**data)
        except pydantic.ValidationError as error:
            first = error.errors()[0]
            raise _field_error(first) from error
        for carrier in self.prices:
            self.price(carrier, required=False)

    @classmethod
    def from_dict(cls, data):
        """Return the assumptions of a dictionary of ``to_dict``."""
        return cls(**data)

    def to_dict(self):
        """Return what differs from the defaults, as plain data."""
        fields = type(self).model_fields
        return {
            name: _plain(getattr(self, name))
            for name, field in fields.items()
            if getattr(self, name) != field.get_default(call_default_factory=True)
        }

    @classmethod
    def schema(cls):
        """Return the JSON Schema (draft 2020-12) of ``to_dict``."""
        schema = cls.model_json_schema()
        for name in AMOUNTS:
            schema["properties"][name] = _quantity_schema(AMOUNTS[name])
        schema["properties"]["prices"] = {
            "type": "object",
            "additionalProperties": _quantity_schema(None),
        }
        return schema

    def price(self, carrier, required=True):
        """Return the price of ``carrier`` in SI, a number or an array along the demand.

        A carrier nobody priced raises ``ValidationError`` (code ``missing_assumption``) naming it,
        or gives ``None`` with ``required=False``.
        """
        if carrier not in CARRIERS:
            raise ValidationError(
                f"assumptions.prices: carrier = {carrier!r}; expected one of "
                f"{join_names(CARRIERS)}{did_you_mean(carrier, CARRIERS)}",
                path=f"assumptions.prices.{carrier}",
                suggestions=close_matches(carrier, CARRIERS),
                code="unknown_name",
            )
        path = f"assumptions.prices.{carrier}"
        if carrier in self.prices:
            return _in_si(self.prices[carrier], CARRIERS[carrier], path)
        if required:
            raise ValidationError(
                f"{path} is missing; expected a value from the user (it has no default)",
                path=path,
                code="missing_assumption",
            )
        return None

    def co2_cost(self):
        """Return ``co2_price`` in SI [currency/kg], or ``None`` when nobody gave it."""
        return self._si("co2_price")

    def emission_factor(self, required=False):
        """Return ``electricity_emission_factor`` in SI [kg/J].

        Nobody giving it is ``None``, or ``missing_assumption`` with ``required=True``.
        """
        if required:
            require(self, "electricity_emission_factor")
        return self._si("electricity_emission_factor")

    def factor(self, name):
        """Return the cost factor ``name`` in SI, or raise ``missing_assumption`` naming it."""
        return self._si(name, require(self, name))

    def _si(self, name, amount=None):
        """Return the field ``name`` in SI, or ``None`` when it is not given."""
        amount = getattr(self, name) if amount is None else amount
        if amount is None:
            return None
        return _in_si(amount, AMOUNTS[name], f"assumptions.{name}")

    def source_of(self, name):
        """Return the source of the cost factor ``name``; a factor changed by the user is theirs."""
        if getattr(self, name) == type(self).model_fields[name].default:
            return COST_SOURCES[name]
        return f"assumptions.{name}"


def _field_error(first):
    """Return the ``ValidationError`` of the first problem pydantic found."""
    path = f"assumptions.{first['loc'][0]}"
    error = first.get("ctx", {}).get("error")
    if isinstance(error, ValidationError):
        return ValidationError(f"{path}: {error}", path=path, code=error.code)
    code = "out_of_bounds" if "expected 0 or more" in first["msg"] else None
    return ValidationError(
        f"{path}: {first['msg']}",
        path=path,
        code=code or FIELD_CODES.get(first["type"], "invalid_value"),
    )


def _quantity(amount, path):
    """Return ``amount`` as a ``Quantity``; a plain number or a text raises ``invalid_value``."""
    if isinstance(amount, units.Quantity):
        return amount
    if isinstance(amount, dict):
        return units.Quantity.from_dict(amount)
    raise ValidationError(
        f"assumptions.{path}: value = {amount!r}; expected {units.QUANTITY_FORM}",
        path=f"assumptions.{path}",
        code="invalid_value",
    )


def _quantity_schema(si_unit):
    """Return the schema of a quantity of the SI unit ``si_unit``, any unit when it is ``None``."""
    allowed = [unit for unit in units.names() if si_unit is None or units.si_unit(unit) == si_unit]
    return {
        "type": "object",
        "required": ["value", "unit"],
        "additionalProperties": False,
        "properties": {
            "value": {
                "anyOf": [{"type": "number"}, {"type": "array", "items": {"type": "number"}}]
            },
            "unit": {"enum": allowed},
        },
    }


def _plain(data):
    """Return ``data`` with every ``Quantity`` as its dict."""
    if isinstance(data, units.Quantity):
        return data.to_dict()
    if isinstance(data, dict):
        return {key: _plain(item) for key, item in data.items()}
    return data


def _in_si(amount, unit, path):
    """Return ``amount``, a ``Quantity``, in the SI ``unit``: a float, or an array for a profile."""
    value = units.value_in_si(amount, unit, path)
    return np.asarray(value, dtype=float) if isinstance(value, np.ndarray) else value


def resolve(assumptions):
    """Return ``assumptions``, or the sourced defaults when it is ``None``."""
    if assumptions is None:
        return Assumptions()
    if not isinstance(assumptions, Assumptions):
        raise ValidationError(
            f"assumptions = {assumptions!r}; expected an Assumptions or None", path="assumptions"
        )
    return assumptions


def require(assumptions, name):
    """Return the assumption ``name``, or raise ``ValidationError`` saying the user must give it."""
    value = getattr(assumptions, name)
    if value is None:
        raise ValidationError(
            f"assumptions.{name} is None; expected a value from the user (it has no default)",
            path=f"assumptions.{name}",
            code="missing_assumption",
        )
    return value


def discounting(assumptions, discount_rate, lifetime):
    """Return ``(rate, years)``: the explicit arguments, else those of ``assumptions``.

    A value given nowhere raises ``ValidationError`` (code ``missing_assumption``); a negative rate
    or a lifetime under one year raises ``ValidationError``.
    """
    rate = discount_rate if discount_rate is not None else require(assumptions, "discount_rate")
    years = lifetime if lifetime is not None else require(assumptions, "lifetime_years")
    if rate < 0:
        raise ValidationError(
            f"discount_rate = {rate}; expected a rate of 0 or more", path="discount_rate"
        )
    if years < 1:
        raise ValidationError(f"lifetime = {years}; expected 1 year or more", path="lifetime")
    return rate, years
