"""A gas from its composition: molar mass, normal and ideal-gas density, heating value and CO2.

A composition maps a species to its mole fraction. The formulas of a fluid that carries a gas
live here; ``gemini.types.Fluid`` calls them once per fluid, so they run on plain numbers, except
``ideal_gas_density``, which a stream calls with its pressure and temperature.
"""

from gemini import ops
from gemini.ops import Constant
from gemini.physics import constants
from gemini.physics.combustion import METHANE_MOLAR_MASS

MOLAR_GAS_CONSTANT = Constant(
    "MOLAR_GAS_CONSTANT", 8.314462618, "J/mol/K", "molar gas constant (CODATA 2018)"
)

NORMAL_TEMPERATURE = 273.15
"""Temperature [K] of a normal cubic metre: 0 degC, the normal state of DIN 1343."""

NORMAL_PRESSURE = 101325.0
"""Pressure [Pa] of a normal cubic metre: 1.01325 bar(a), the normal state of DIN 1343."""

SPECIES = {
    "CH4": (float(METHANE_MOLAR_MASS), 802.3e3, 1),
    "C2H6": (0.030069, 1428.7e3, 2),
    "C3H8": (0.044096, 2043.2e3, 3),
    "CO2": (float(constants.CO2_MOLAR_MASS), 0.0, 0),
    "N2": (0.0280134, 0.0, 0),
    "O2": (0.0319988, 0.0, 0),
}
"""Molar mass [kg/mol], lower heating value [J/mol] and carbon atoms burnt to CO2 per species.

Heating values: gas-phase standard enthalpy of combustion of the NIST Chemistry WebBook (890.3,
1560.7 and 2219.2 kJ/mol) less the latent heat of the water formed (44.0 kJ/mol H2O). Molar masses:
IUPAC 2013 standard atomic weights. CO2 and N2 do not burn; the CO2 of a gas is carried through.
"""

GRID_COMPOSITION = {
    "CH4": 82.5204 / 100.0307,
    "C2H6": 3.9562 / 100.0307,
    "C3H8": 1.2752 / 100.0307,
    "CO2": 1.1916 / 100.0307,
    "N2": 11.0873 / 100.0307,
}
"""Mole fractions of grid gas: a measured analysis, not a Dutch or a design figure.

NGN Netzgesellschaft Niederrhein mbH, Gasbeschaffenheiten NKP07, January 2026 (published 19 March
2026): CH4 82.5204, C2H6 3.9562, C3H8 0.8211, CO2 1.1916, N2 11.0873 mol%, the published molar mass
18.7155 kg/kmol and CO2 factor 0.056474 t/GJ. The 0.4541 mol% of butanes and heavier is lumped into
C3H8, and the analysis, which sums to 100.0307 mol%, is scaled to one.
"""

COMPOSITION_TOLERANCE = 1e-9
"""Largest distance from one [-] of the sum of a composition; numerical, not physical."""


def molar_mass(composition: dict) -> float:
    """Return the molar mass [kg/mol] of a gas, the mole-weighted sum over its species.

    Parameters
    ----------
    composition : dict
        Mole fraction [-] per species of ``SPECIES``, summing to one.

    Returns
    -------
    float
        Molar mass [kg/mol].

    Notes
    -----
    Definition of the molar mass of a mixture. Valid for any composition of known species. Source:
    a plain mole balance; no published source is needed.
    """
    return sum(fraction * SPECIES[name][0] for name, fraction in composition.items())


@ops.physics
def ideal_gas_density(pressure: float, temperature: float, mass_per_mole: float) -> float:
    """Return the ideal-gas density [kg/m3], ``rho = p M / (R T)``.

    Parameters
    ----------
    pressure : float
        Absolute pressure [Pa], nonnegative.
    temperature : float
        Absolute temperature [K], positive.
    mass_per_mole : float
        Molar mass [kg/mol], positive.

    Returns
    -------
    float
        Density [kg/m3].

    Notes
    -----
    Ideal-gas law. Valid well below the critical pressure of the gas; methane and CO2 near
    atmospheric pressure deviate by less than 1 %. Reference: any thermodynamics text, for example
    Cengel and Boles, Thermodynamics, section 3-6.
    """
    return pressure * mass_per_mole / (MOLAR_GAS_CONSTANT * temperature)


def normal_density(
    composition: dict,
    temperature: float = NORMAL_TEMPERATURE,
    pressure: float = NORMAL_PRESSURE,
) -> float:
    """Return the density [kg/Nm3] of a gas at its reference conditions, by default normal ones.

    Parameters
    ----------
    composition : dict
        Mole fraction [-] per species of ``SPECIES``.
    temperature, pressure : float
        Reference conditions [K, Pa] of the cubic metre a gas-liquid ratio counts; by default
        the normal state, 0 degC and 1.01325 bar(a). Pass 288.15 K for standard conditions.

    Returns
    -------
    float
        Ideal-gas density at normal conditions [kg/m3].

    Notes
    -----
    ``ideal_gas_density`` at the reference conditions.

    Validity: The published normal density of a real gas is up to about 0.5 % higher.
    Source: DIN 1343, Reference conditions, normal conditions, normal volume: normal temperature
    273.15 K and normal pressure 101325 Pa. ISO 13443 names other reference conditions, 288.15 K.
    """
    return ideal_gas_density(pressure, temperature, molar_mass(composition))


def lower_heating_value(composition: dict) -> float:
    """Return the lower heating value [J/kg] of a gas.

    Parameters
    ----------
    composition : dict
        Mole fraction [-] per species of ``SPECIES``.

    Returns
    -------
    float
        Heat of complete combustion per kilogram of gas, the water leaving as vapour [J/kg].

    Notes
    -----
    Mole-weighted sum of the heating values of ``SPECIES`` over the molar mass of the gas.

    Validity: Any composition of known species; zero for a gas that does not burn.
    Source: Heating values of the NIST Chemistry WebBook, see ``SPECIES``.
    """
    heat = sum(fraction * SPECIES[name][1] for name, fraction in composition.items())
    return heat / molar_mass(composition)


def combustion_co2(composition: dict) -> float:
    """Return the CO2 [kg] that complete combustion forms per kilogram of gas.

    Parameters
    ----------
    composition : dict
        Mole fraction [-] per species of ``SPECIES``.

    Returns
    -------
    float
        Kilograms of CO2 formed per kilogram of gas [-]; the CO2 already in the gas is not counted.

    Notes
    -----
    Stoichiometry: one mole of CO2 per carbon atom that burns.

    Validity: Complete combustion of the species of ``SPECIES``.
    Source: Stoichiometry; no published source is needed.
    """
    carbon = sum(fraction * SPECIES[name][2] for name, fraction in composition.items())
    return carbon * constants.CO2_MOLAR_MASS / molar_mass(composition)


def mass_fraction(composition: dict, species: str) -> float:
    """Return the mass fraction [-] of one species in a gas.

    Parameters
    ----------
    composition : dict
        Mole fraction [-] per species of ``SPECIES``.
    species : str
        A species of ``SPECIES``; one the gas does not hold has the fraction zero.

    Returns
    -------
    float
        Mass of the species per mass of gas [-].

    Notes
    -----
    Mole fraction times the molar mass of the species over the molar mass of the gas.

    Validity: Any composition of known species.
    Source: A plain mass balance; no published source is needed.
    """
    return composition.get(species, 0.0) * SPECIES[species][0] / molar_mass(composition)


def emission_per_energy(composition: dict) -> float:
    """Return the CO2 [kg] a burner emits per joule of fuel energy of a gas.

    Parameters
    ----------
    composition : dict
        Mole fraction [-] per species of ``SPECIES``; the gas must burn.

    Returns
    -------
    float
        ``(f_CO2 + x_CO2) / LHV`` [kg/J]: the CO2 formed plus the CO2 the gas carries.

    Notes
    -----
    A kilogram of gas gives its heating value and all of its carbon as CO2.

    Validity: Complete combustion of a gas with a positive heating value.
    Source: Stoichiometry; no published source is needed.
    """
    emitted = combustion_co2(composition) + mass_fraction(composition, "CO2")
    return emitted / lower_heating_value(composition)


@ops.physics
def gas_mass_fraction(ratio: float, density_normal: float, liquid_density: float) -> float:
    """Return the gas mass fraction [-] of a gas-liquid ratio, ``x = R rho_n / (rho_l + R rho_n)``.

    Parameters
    ----------
    ratio : float
        Gas-liquid ratio [Nm3 of gas per m3 of liquid], nonnegative.
    density_normal : float
        Gas density at normal conditions [kg/Nm3], positive.
    liquid_density : float
        Liquid density [kg/m3], positive.

    Returns
    -------
    float
        Mass of free gas per mass of mixture [-], in [0, 1).

    Notes
    -----
    One cubic metre of liquid holds ``R rho_n`` kilograms of gas.

    Validity: Any nonnegative ratio.
    Source: A plain mass balance; no published source is needed.
    """
    gas = ratio * density_normal
    return gas / (liquid_density + gas)


@ops.physics
def gas_liquid_ratio(fraction: float, density_normal: float, liquid_density: float) -> float:
    """Return the gas-liquid ratio [Nm3/m3] of a gas mass fraction, the inverse of the above.

    Parameters
    ----------
    fraction : float
        Gas mass fraction ``x`` [-], in [0, 1).
    density_normal : float
        Gas density at normal conditions [kg/Nm3], positive.
    liquid_density : float
        Liquid density [kg/m3], positive.

    Returns
    -------
    float
        ``R = x rho_l / ((1 - x) rho_n)`` [Nm3 of gas per m3 of liquid].

    Notes
    -----
    Solves ``gas_mass_fraction`` for the ratio.

    Validity: x below one.
    Source: A plain mass balance; no published source is needed.
    """
    return fraction * liquid_density / ((1 - fraction) * density_normal)


AIR_COMPOSITION = {"N2": 0.79, "O2": 0.21}
"""Dry air as mole fractions, argon and CO2 counted as nitrogen (Incropera et al., Fundamentals of
Heat and Mass Transfer, 7th ed., table A.4 lists air as one substance)."""

AIR_SPECIFIC_HEAT = 1007.0
"""Specific heat [J/kg/K] of air at 300 K and 1 atm: Incropera et al., 7th ed., table A.4."""


@ops.physics
def species_flow(mass_flow, composition, species):
    """Return the mass flow [kg/s] of ``species`` in a gas stream; zero without a composition."""
    if composition is None:
        return 0.0
    return mass_flow * mass_fraction(composition, species)


def composition_of_masses(masses):
    """Return the mole fractions of a gas whose species have the mass shares ``masses``."""
    moles = {name: share / SPECIES[name][0] for name, share in masses.items()}
    total = sum(moles.values())
    return {name: amount / total for name, amount in moles.items()}
