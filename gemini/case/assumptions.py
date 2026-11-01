"""The assumptions of a case: finance (money) and emissions (by species)."""

from typing import Annotated, Any

from gemini.case._utils.fields import Q, QMap
from gemini.case._utils.kinds import EQUIPMENT_KINDS
from gemini.case._utils.section import Section

_NON_NEGATIVE = (0.0, False)


def _factor(quantity):
    """Return the type of a constant of ``quantity`` that is 0 or more."""
    return Annotated[Any, Q(quantity, minimum=_NON_NEGATIVE)]


def _price(quantity):
    """Return the type of a constant or a profile of ``quantity`` that is 0 or more."""
    return Annotated[Any, Q(quantity, profile=True, minimum=_NON_NEGATIVE)]


PER_LENGTH = _factor("money_per_length")
PER_POWER = _factor("money_per_power")
PER_CONDUCTANCE = _factor("money_per_conductance")
PER_VOLUME = _factor("money_per_volume")
AMOUNT = _factor("money")
RATIO = _factor("ratio")
PER_ENERGY = _price("money_per_energy")
PER_MASS = _price("money_per_mass")
MASS_PER_ENERGY = _price("mass_per_energy")


class Capex(Section):
    """One capex factor per equipment kind, each per capacity, per metre or a fixed amount.

    The keys are the equipment kinds of ``gemini.case._utils.kinds.EQUIPMENT_KINDS``, each with its
    cost basis: per W of capacity (of shaft power for a pump, of electric capacity for a CHP),
    per metre, per W/K, per m3, or a fixed amount. A factor is a ``Quantity`` such as
    ``Quantity(0.67, "EUR/W")``; the currency is a label and nothing converts between currencies.
    """

    where = "assumptions.finance.capex"
    drilling: PER_LENGTH = None
    production_pump: PER_POWER = None
    injection_pump: PER_POWER = None
    circulation_pump: PER_POWER = None
    heat_pump: PER_POWER = None
    boiler: PER_POWER = None
    electric_boiler: PER_POWER = None
    chp: PER_POWER = None
    absorption_chiller: PER_POWER = None
    adsorption_chiller: PER_POWER = None
    compression_chiller: PER_POWER = None
    heat_exchanger: PER_CONDUCTANCE = None
    cooler: PER_POWER = None
    pipe: PER_LENGTH = None
    thermal_storage: PER_VOLUME = None
    ice_storage: PER_VOLUME = None
    degasser: AMOUNT = None
    flare: AMOUNT = None
    gas_makeup: AMOUNT = None


class Opex(Section):
    """Operating costs: a fixed share of capex per kind, and the price of what is bought.

    ``fixed`` maps an equipment kind to its yearly cost as a share of that kind's capex (a
    ``Quantity`` in ``%/yr``). ``electricity``, ``gas``, ``chemical``, ``waste_disposal`` and
    ``co2`` are a constant ``Quantity`` or a profile on the steps of ``time``.
    """

    where = "assumptions.finance.opex"
    fixed: Annotated[dict[str, float] | None, QMap("annual_rate", tuple(EQUIPMENT_KINDS))] = None
    electricity: PER_ENERGY = None
    gas: PER_ENERGY = None
    chemical: PER_MASS = None
    waste_disposal: PER_MASS = None
    co2: PER_MASS = None


class Revenue(Section):
    """What a unit of delivered heat and cold earns, a constant or a profile."""

    where = "assumptions.finance.revenue"
    heat: PER_ENERGY = None
    cold: PER_ENERGY = None


class Allocation(Section):
    """How a plant that delivers heat and cold shares its cost.

    ``heat_cost_share`` is the share [-] of the plant cost charged to heat; the rest goes to cold.
    """

    where = "assumptions.finance.allocation"
    heat_cost_share: Annotated[Any, Q("fraction", minimum=(0.0, False), maximum=(1.0, False))] = (
        None
    )


class Finance(Section):
    """Everything that is money: currency label, rates, lifetime, factors, prices and revenue.

    Attributes
    ----------
    currency : str or None
        A label for every amount of the case.
    discount_rate : float or None
        Real discount rate per year [-].
    lifetime : float or None
        Years of operation, stored in seconds.
    price_year : int or None
        The year the factors are priced in.
    """

    where = "assumptions.finance"
    currency: str | None = None
    discount_rate: RATIO = None
    lifetime: Annotated[Any, Q("duration", minimum=(0.0, True))] = None
    price_year: int | None = None
    capex: Capex | None = None
    opex: Opex | None = None
    revenue: Revenue | None = None
    allocation: Allocation | None = None


class CO2(Section):
    """The emissions of CO2: ``electricity`` is the mass per energy of grid electricity bought."""

    where = "assumptions.emissions.CO2"
    electricity: MASS_PER_ENERGY = None


class CH4(Section):
    """The emissions of CH4: ``gwp`` is the CO2-equivalent [-] of a kilogram released."""

    where = "assumptions.emissions.CH4"
    gwp: RATIO = None


_CO2, _CH4 = CO2, CH4
"""The two species classes under names that the fields of ``Emissions`` do not shadow."""


class Emissions(Section):
    """Emissions by species, with the names of ``environment.fluid.gas``."""

    where = "assumptions.emissions"
    CO2: _CO2 | None = None
    CH4: _CH4 | None = None


class Assumptions(Section):
    """The finance and the emissions assumptions; the package holds no default of either."""

    where = "assumptions"
    finance: Finance | None = None
    emissions: Emissions | None = None
