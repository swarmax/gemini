"""Treatment relations: gas separation, cyclone sand removal, and dosing."""

from gemini import ops
from gemini.physics.separation import split_flow


@ops.physics
def degasser_split(
    mass_flow: float, gas_mass_fraction: float, efficiency: float
) -> tuple[float, float, float]:
    """Return the liquid flow, the separated gas flow and the gas fraction left in the liquid.

    ``gas = eta x m``, ``liquid = m - gas`` and ``x_left = (1 - eta) x / (1 - eta x)``.

    Parameters
    ----------
    mass_flow : float
        Inlet mass flow [kg/s].
    gas_mass_fraction : float
        Free gas mass fraction ``x`` of the inlet [-], in [0, 1].
    efficiency : float
        Share ``eta`` of the free gas that leaves through the gas outlet [-], in [0, 1].

    Returns
    -------
    tuple of float
        Liquid outlet mass flow [kg/s], gas outlet mass flow [kg/s] and gas mass fraction of the
        liquid outlet [-]; the free gas is conserved.

    Notes
    -----
    Lumped vessel performance: no residence time, level or solubility (Henry's law); dissolved
    gas stays in the liquid. Retained GEMINI formulation of an ideal split of the free gas.

    Validity: mass_flow nonnegative; gas_mass_fraction and efficiency in [0, 1], not both equal to
    one (the code divides by 1 - eta x).
    """
    liquid, gas = split_flow(mass_flow, efficiency * gas_mass_fraction)
    remaining = (1 - efficiency) * gas_mass_fraction / (1 - efficiency * gas_mass_fraction)
    return liquid, gas, remaining


@ops.physics
def cyclone_sand(
    efficiency: float, sand_concentration: float, liquid_flow: float
) -> tuple[float, float]:
    """Return the sand removal rate and the residual sand concentration of a cyclone.

    ``rate = eta c Q`` and ``c_out = (1 - eta) c``.

    Parameters
    ----------
    efficiency : float
        Lumped separation efficiency ``eta`` over the size distribution [-], in [0, 1].
    sand_concentration : float
        Sand concentration ``c`` of the inlet liquid [kg/m3].
    liquid_flow : float
        Liquid volume flow ``Q`` [m3/s], see ``fluid.liquid_volume_flow``.

    Returns
    -------
    tuple of float
        Sand removal rate [kg/s] and residual concentration [kg/m3].

    Notes
    -----
    The grade-efficiency curve is lumped into one constant efficiency, so the cut size does not
    follow the flow. Reference: Svarovsky (2000), Solid-Liquid Separation, 4th ed., chapter
    "Hydrocyclones"; retained GEMINI formulation.

    Validity: efficiency in [0, 1]; sand_concentration and liquid_flow nonnegative; no division
    occurs.
    """
    return efficiency * sand_concentration * liquid_flow, (1 - efficiency) * sand_concentration


@ops.physics
def dosing_flows(
    dose: float, mass_flow: float, product_concentration: float
) -> tuple[float, float]:
    """Return the product and the active mass flow of a chemical dosing.

    ``m_product = dose m`` and ``m_active = w m_product``.

    Parameters
    ----------
    dose : float
        Mass of product per mass of treated fluid [-] (1 ppm = 1e-6).
    mass_flow : float
        Treated mass flow [kg/s].
    product_concentration : float
        Mass fraction ``w`` of active substance in the product [-].

    Returns
    -------
    tuple of float
        Product mass flow and active substance mass flow [kg/s].

    Notes
    -----
    Mass-proportional dosing as in inhibitor programmes (Gallup, 2009, Geothermics 38,
    326-334); the dosed mass is not added to the stream.

    Validity: dose and mass_flow nonnegative; product_concentration in [0, 1]; no division occurs.
    """
    product = dose * mass_flow
    return product, product_concentration * product
