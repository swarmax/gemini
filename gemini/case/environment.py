"""The environment of a case: ground, reservoir, fluid and air."""

import math
from typing import Annotated, Any

from pydantic import field_validator

from gemini.case._utils.access import require
from gemini.case._utils.fields import Q
from gemini.case._utils.kinds import GAS_SPECIES
from gemini.case._utils.section import Section
from gemini.errors import ValidationError
from gemini.physics import ground

_POSITIVE = (0.0, True)
_NON_NEGATIVE = (0.0, False)


class Ground(Section):
    """The undisturbed ground: the surface temperature and the geothermal gradient.

    Attributes
    ----------
    surface_temperature : float or None
        Mean temperature at the surface [K].
    gradient : float or None
        Geothermal gradient [K/m].
    """

    where = "environment.ground"
    surface_temperature: Annotated[Any, Q("temperature", minimum=_POSITIVE)] = None
    gradient: Annotated[Any, Q("temperature_gradient")] = None


class Reservoir(Section):
    """The reservoir at its reference depth.

    ``temperature`` is optional: without it the temperature at a depth comes from the ground.

    Attributes
    ----------
    reference_depth : float or None
        True vertical depth [m] of ``pressure`` and ``temperature``.
    thickness : float or None
        Gross thickness [m].
    permeability : float or None
        Permeability [m2].
    pressure : float or None
        Absolute pressure [Pa] at the reference depth.
    temperature : float or None
        Temperature [K] at the reference depth.
    """

    where = "environment.reservoir"
    reference_depth: Annotated[Any, Q("length")] = None
    thickness: Annotated[Any, Q("length", minimum=_POSITIVE)] = None
    permeability: Annotated[Any, Q("permeability", minimum=_POSITIVE)] = None
    pressure: Annotated[Any, Q("pressure", minimum=_NON_NEGATIVE)] = None
    temperature: Annotated[Any, Q("temperature", minimum=_POSITIVE)] = None


class Fluid(Section):
    """The reservoir fluid: brine properties and the dissolved gas.

    Attributes
    ----------
    density : float or None
        Brine density [kg/m3].
    viscosity : float or None
        Brine viscosity [Pa s].
    gas_liquid_ratio : float or None
        Gas per liquid volume at standard conditions [-].
    gas : dict or None
        Mole fraction of each species of ``GAS_SPECIES`` (``CH4``, ``CO2``, ``N2``, ``H2S``); the
        fractions sum to 1.
    """

    where = "environment.fluid"
    density: Annotated[Any, Q("density")] = None
    viscosity: Annotated[Any, Q("viscosity")] = None
    gas_liquid_ratio: Annotated[Any, Q("gas_liquid_ratio")] = None
    gas: dict[str, float] | None = None

    @field_validator("gas")
    @classmethod
    def _checked_gas(cls, gas):
        """Raise unless ``gas`` has known species and fractions that sum to 1."""
        if gas is None:
            return gas
        unknown = [name for name in gas if name not in GAS_SPECIES]
        if unknown:
            raise ValidationError(
                f"gas: species {unknown[0]!r} is unknown; expected one of {', '.join(GAS_SPECIES)}",
                code="unknown_name",
            )
        if any(not 0 <= fraction <= 1 for fraction in gas.values()) or not math.isclose(
            sum(gas.values()), 1.0, abs_tol=1e-9
        ):
            raise ValidationError(
                f"gas = {gas}; expected mole fractions in [0, 1] that sum to 1",
                code="out_of_bounds",
            )
        return gas


class Air(Section):
    """The outside air.

    Attributes
    ----------
    temperature : float or ndarray or None
        Temperature [K]: a constant, or a profile on the steps of ``time``.
    """

    where = "environment.air"
    temperature: Annotated[Any, Q("temperature", profile=True, minimum=_POSITIVE)] = None


class Environment(Section):
    """Ground, reservoir, fluid and air; every part is optional.

    ``temperature_at`` and ``pressure_at`` apply the two rules of ``gemini.physics.ground`` to the
    values of the case.
    """

    where = "environment"
    ground: Ground | None = None
    reservoir: Reservoir | None = None
    fluid: Fluid | None = None
    air: Air | None = None

    def temperature_at(self, depth):
        """Return the reservoir temperature [K] at ``depth`` [m].

        The given ``reservoir.temperature`` shifted by the gradient from the reference depth, or
        ``ground.surface_temperature + gradient * depth``. Raises ``missing_value`` naming what is
        absent.
        """
        gradient = require(self, "ground.gradient", "environment")
        reference = require(self, "reservoir.reference_depth", "environment")
        given = self.reservoir.temperature
        surface = (
            None
            if given is not None
            else require(self, "ground.surface_temperature", "environment")
        )
        return float(ground.reservoir_temperature(surface, gradient, depth, reference, given))

    def pressure_at(self, depth):
        """Return the reservoir pressure [Pa] at ``depth`` [m].

        ``reservoir.pressure + fluid.density * g * (depth - reference_depth)``. Raises
        ``missing_value`` naming what is absent.
        """
        pressure = require(self, "reservoir.pressure", "environment")
        reference = require(self, "reservoir.reference_depth", "environment")
        density = require(self, "fluid.density", "environment")
        return float(ground.reservoir_pressure(pressure, density, depth, reference))
