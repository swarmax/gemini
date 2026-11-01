"""Immutable stream composition and cached constant-property models."""

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticError
from pydantic import model_serializer, model_validator

from gemini import units
from gemini._utils.strings import did_you_mean, join_names
from gemini.errors import ValidationError
from gemini.physics import constants, gas
from gemini.physics.chemistry import henry_constant
from gemini.physics.fluid import DEFAULT_LIQUID_DENSITY, FluidProperties, mixture_density
from gemini.types.quantities import (
    Density,
    Fraction,
    GasLiquidRatio,
    Pressure,
    SpecificHeat,
    Temperature,
    ThermalConductivity,
    Viscosity,
)

_FIELD_UNITS = {
    "density": "kg/m3",
    "viscosity": "Pa.s",
    "specific_heat": "J/kg/K",
    "thermal_conductivity": "W/m/K",
    "gas_liquid_ratio": "-",
}
"""The SI unit of each ``Fluid`` field that takes a unit string."""


class Fluid(BaseModel):
    """Stream fluid; composition is descriptive unless the property model uses it.

    Salinity, dissolved CO2 and free gas are mass fractions. Glycol is a volume fraction,
    matching the cited manufacturer table. Constant STP does not infer brine density or viscosity
    from salt concentration; supply measured values. ``density``, ``viscosity``, ``specific_heat``
    and ``thermal_conductivity`` describe the liquid of a brine or water fluid and the gas of a gas
    fluid; a mixture density is a computed property, never an input. Numbers are SI.

    Free gas is given as ``gas_liquid_ratio`` (normal m3 of free gas per m3 of produced liquid, at
    0 degC and 1.01325 bar a) with ``gas_composition`` (mole fractions summing to one, the species
    of ``gas.SPECIES``), which give ``gas_mass_fraction``, or as ``gas_mass_fraction`` directly,
    never both. ``co2_mass_fraction`` is another thing: the CO2 dissolved in the liquid, which
    corrosion reads. The CO2 of the free gas is part of ``gas_composition``.

    ``gas`` is a gas fluid with a ``gas_composition``, such as the gas outlet of a ``Degasser``. Its
    density at a stream's pressure and temperature is ``density_at``, ideal-gas unless ``density``
    is given, and its ``properties`` snapshot holds the density at normal conditions.

    ``grid_composition`` marks a stream on which a burner may draw grid gas, and says what that
    gas is. ``GasGrid`` and ``GasMakeup`` set it.

    ``steam`` marks water vapour, such as the gas outlet of a flash ``Separator``. Its
    constant property snapshot is the liquid-water default and does not describe vapour:
    steam equipment takes enthalpy and entropy from the steam tables of ``modules/power``, so do
    not convert a steam stream's volume flow or audit its latent heat with ``cp_l * T``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    kind: Literal["brine", "water", "glycol_water", "steam", "gas"] = "brine"
    salinity: Fraction = 0.0
    co2_mass_fraction: Fraction = 0.0
    gas_mass_fraction: Fraction = Field(0.0, lt=1)
    gas_liquid_ratio: GasLiquidRatio | None = None
    gas_composition: dict[str, Fraction] | None = None
    grid_composition: dict[str, Fraction] | None = None
    glycol_fraction: Fraction = 0.0
    property_model: Literal["constant_stp"] = "constant_stp"
    density: Density | None = None
    viscosity: Viscosity | None = None
    specific_heat: SpecificHeat | None = None
    thermal_conductivity: ThermalConductivity | None = None

    def __init__(self, **data):
        """Build a fluid; a value that does not fit raises ``gm.errors.ValidationError``."""
        try:
            super().__init__(**data)
        except PydanticError as error:
            raise ValidationError(f"Fluid: {error}", code=_code_of(error)) from error

    def __hash__(self):
        """Hash every field; a composition by its items, because a dictionary has no hash."""
        return hash(
            tuple(
                tuple(sorted(value.items())) if isinstance(value, dict) else value
                for value in self.__dict__.values()
            )
        )

    @model_validator(mode="before")
    @classmethod
    def in_si(cls, data):
        """Convert the unit strings of the quantity fields to SI."""
        if not isinstance(data, dict):
            return data
        return {
            key: units.value_in_si(value, _FIELD_UNITS.get(key), f"Fluid.{key}")
            for key, value in data.items()
        }

    @model_validator(mode="after")
    def composition(self):
        """Reject impossible compositions and derive the mass fraction of a gas-liquid ratio."""
        if self.salinity + self.co2_mass_fraction + self.gas_mass_fraction > 1:
            raise ValueError("Mass fractions must sum to at most one")
        if self.kind != "glycol_water" and self.glycol_fraction:
            raise ValueError("Glycol fraction requires glycol_water")
        if self.kind == "glycol_water" and self.glycol_fraction != 0.3:
            raise ValueError("constant_stp currently supports only 30% glycol by volume")
        self._check_gas()
        if self.gas_liquid_ratio is not None:
            fraction = gas.gas_mass_fraction(
                self.gas_liquid_ratio, self.normal_density(), self._liquid_density()
            )
            object.__setattr__(self, "gas_mass_fraction", fraction)
        return self

    def _check_gas(self):
        """Reject a gas description that says too much, too little or something unknown."""
        given = self.gas_liquid_ratio is not None
        if given and "gas_mass_fraction" in self.model_fields_set:
            raise ValidationError("Give gas_liquid_ratio or gas_mass_fraction, not both")
        if given and self.gas_composition is None:
            raise ValidationError("gas_liquid_ratio needs gas_composition")
        if self.kind == "gas" and self.gas_composition is None:
            raise ValidationError("A gas fluid needs gas_composition")
        if self.gas_composition is not None and not given and self.kind != "gas":
            raise ValidationError("gas_composition needs gas_liquid_ratio")
        for composition in (self.gas_composition, self.grid_composition):
            if composition is not None:
                _check_composition(composition)

    @model_serializer(mode="wrap")
    def _without_derived(self, handler):
        """Leave out the mass fraction that a gas-liquid ratio derives, so a copy reads back."""
        data = handler(self)
        if self.gas_liquid_ratio is not None:
            del data["gas_mass_fraction"]
        return data

    def _liquid_density(self):
        return DEFAULT_LIQUID_DENSITY if self.density is None else self.density

    def normal_density(self):
        """Return the density [kg/Nm3] of the gas of this fluid at normal conditions."""
        return gas.normal_density(self.gas_composition)

    def heating_value(self):
        """Return the lower heating value [J/kg] of the gas; zero without a composition."""
        if self.gas_composition is None:
            return 0.0
        return gas.lower_heating_value(self.gas_composition)

    def gas_share(self):
        """Return the mass fraction of gas in a stream of this fluid [-]."""
        return 1.0 if self.kind == "gas" else self.gas_mass_fraction

    def co2_in_gas(self):
        """Return the mass fraction of CO2 in the gas of this fluid [-]; zero without one."""
        if self.gas_composition is None:
            return 0.0
        return gas.mass_fraction(self.gas_composition, "CO2")

    def emission_factor(self):
        """Return the CO2 [kg/J] of burning the gas; zero when it does not burn."""
        if self.heating_value() == 0:
            return 0.0
        return gas.emission_per_energy(self.gas_composition)

    def free_gas(self):
        """Return the gas fluid of the free gas of this fluid; this fluid without a composition.

        NOTE(refactor): the gas keeps the liquid's ``cp_l``, the audit convention of
        ``energy_balance``, which values every stream at ``cp_l``.
        """
        return _free_gas(self)

    def with_grid(self, composition):
        """Return this fluid marked as a stream on which a burner may draw grid gas."""
        return self.model_copy(update={"grid_composition": composition})

    def with_gas_fraction(self, fraction):
        """Return this fluid with the free gas of mass fraction ``fraction`` left in it."""
        update = {"gas_mass_fraction": fraction}
        if self.gas_liquid_ratio is not None:
            update["gas_liquid_ratio"] = gas.gas_liquid_ratio(
                fraction, self.normal_density(), self._liquid_density()
            )
        return self.model_copy(update=update)

    def properties(self, p: Pressure, T: Temperature) -> FluidProperties:
        """Return cached constant SI properties; pressure and temperature are independent."""
        return _properties(self)

    def density_at(self, p: Pressure, T: Temperature):
        """Return the density [kg/m3] of the fluid at ``p`` and ``T``, arrays or traced values too.

        A gas fluid without a given density is an ideal gas of its composition, and a liquid with a
        composition mixes with that gas at ``p`` and ``T``: a low-pressure density would swell the
        mixture at depth. Any other fluid has the constant density of its property snapshot.
        """
        if self.kind == "gas":
            return self.gas_density_at(p, T) if self.density is None else self.density
        if self.gas_composition is None:
            return self.properties(p, T).density
        return mixture_density(
            self._liquid_density(), self.gas_density_at(p, T), self.gas_mass_fraction
        )

    def gas_density_at(self, p: Pressure, T: Temperature):
        """Return the density [kg/m3] of the gas of this fluid at ``p`` and ``T``.

        Ideal-gas for a composition; the constant ``rho_g`` of the property snapshot otherwise.
        """
        if self.gas_composition is None:
            return self.properties(p, T).rho_g
        return gas.ideal_gas_density(p, T, gas.molar_mass(self.gas_composition))

    def corrosion_inputs(self, p: Pressure, T: Temperature) -> dict[str, float]:
        """Convert dissolved CO2 and salt mass fractions for the existing corrosion boundary.

        The Henry-law approximation is evaluated at the inlet temperature. Explicit
        measured gas mole fraction/partial pressure should override it when available. ``T``
        may be an array or a traced value; the fluid and its density stay static.

        NOTE(refactor): dissolved mass fraction is NOT a gas mole fraction. It converts from
        kg/m3 to mol/m3 with the CO2 molar mass, then inverts the existing Henry law.
        """
        rho = self.properties(p, T).rho_l
        dissolved_co2 = self.co2_mass_fraction * rho / constants.CO2_MOLAR_MASS
        return {
            "co2_partial_pressure": dissolved_co2 / henry_constant(T),
            "ionic_strength": self.salinity * rho,
        }


_GLYCOL_30_PROPERTIES = dict(rho_l=1029.85, cp_l=3841, k_l=0.4622, mu_l=0.0016295)

_OVERRIDES = (
    ("density", "rho_l"),
    ("viscosity", "mu_l"),
    ("specific_heat", "cp_l"),
    ("thermal_conductivity", "k_l"),
)


def _code_of(error):
    """Return the code of the gemini error a pydantic error wraps, else ``invalid_value``."""
    for problem in error.errors():
        wrapped = problem.get("ctx", {}).get("error")
        if isinstance(wrapped, ValidationError):
            return wrapped.code
    return "invalid_value"


def _check_composition(composition):
    """Reject a composition of unknown species or whose mole fractions do not sum to one."""
    unknown = [name for name in composition if name not in gas.SPECIES]
    if unknown:
        raise ValidationError(
            f"gas composition: species = {unknown[0]!r}; expected one of "
            f"{join_names(gas.SPECIES)}{did_you_mean(unknown[0], gas.SPECIES)}"
        )
    if abs(sum(composition.values()) - 1) > gas.COMPOSITION_TOLERANCE:
        raise ValidationError("gas composition: mole fractions must sum to one")


@lru_cache(maxsize=256)
def _properties(fluid: Fluid) -> FluidProperties:
    """Return the constant property snapshot of a fluid, cached by its complete value.

    NOTE(refactor): ``glycol_water`` uses DOWFROST HD reference values for 30% propylene
    glycol by volume at 40 C, frozen rather than a temperature-dependent glycol correlation:
    https://www.dow.com/content/dam/dcc/documents/en-us/productdatasheet/180/
    180-01315-01-dowfrost-hd-tds.pdf (table, page 3).
    """
    values = {"gmf": fluid.gas_mass_fraction}
    if fluid.kind == "glycol_water":
        values.update(_GLYCOL_30_PROPERTIES)
    if fluid.gas_composition is not None:
        values["rho_g"] = fluid.normal_density()
    if fluid.kind == "gas":
        values["rho_l"] = fluid.normal_density()
    for field, name in _OVERRIDES:
        value = getattr(fluid, field)
        if value is not None:
            values[name] = value
    return FluidProperties(**values)


@lru_cache(maxsize=256)
def _free_gas(fluid: Fluid) -> Fluid:
    """Return the gas fluid of the free gas of ``fluid``, cached by its complete value."""
    if fluid.gas_composition is None:
        return fluid
    return Fluid(
        kind="gas",
        gas_composition=fluid.gas_composition,
        specific_heat=fluid.properties(0, 0).cp_l,
    )


def grid_gas(composition):
    """Return the gas fluid of a gas grid of ``composition``, marked as grid gas."""
    return Fluid(kind="gas", gas_composition=composition, grid_composition=composition)


AIR = Fluid(kind="gas", gas_composition=gas.AIR_COMPOSITION, specific_heat=gas.AIR_SPECIFIC_HEAT)
FLUE_CO2 = Fluid(kind="gas", gas_composition={"CO2": 1.0})
"""What a burner releases, as the CO2 that leaves it: combustion air is not modelled."""

BRINE = Fluid()
WATER = Fluid(kind="water")
GLYCOL_30 = Fluid(kind="glycol_water", glycol_fraction=0.3)
STEAM = Fluid(kind="steam")
