"""Saturated water and steam properties from IAPWS-IF97 and wet steam expansion.

Every function takes and returns SI values: pressure [Pa], temperature [K], specific enthalpy
[J/kg] and specific entropy [J/kg/K]. The equations are the exact IAPWS-IF97 equations, not
fits to them, so they reproduce the IF97 verification values to their nine printed digits:

- region 4 saturation pressure (IF97 eq. 30) and saturation temperature (eq. 31);
- region 1 compressed liquid basic equation (eq. 7, table 2) for enthalpy and entropy;
- region 2 vapour basic equation (eqs. 15 to 17, tables 10 and 11) for enthalpy and entropy,
  with the B23 boundary equation (eq. 5) that limits region 2 above 623.15 K.

Reference: IAPWS (2007), Revised Release on the IAPWS Industrial Formulation 1997 for the
Thermodynamic Properties of Water and Steam (IAPWS-R7-97(2012)); Wagner, W. et al. (2000),
The IAPWS Industrial Formulation 1997, J. Eng. Gas Turbines Power 122, 150-182.

Saturated properties need regions 1 and 2, which border the saturation line only up to
623.15 K (16.529 MPa); region 3 is not implemented, so saturation states above 623.15 K raise
``PhysicsError``. Geothermal flash plants operate far below this limit (separators at
0.2 to 2 MPa, condensers at 5 to 15 kPa). All properties are those of pure water; dissolved
salts and non-condensable gases are not represented.
"""

from dataclasses import dataclass

from gemini import ops, units
from gemini.errors import PhysicsError
from gemini.ops import Constant

DEFAULT_TURBINE_EFFICIENCY = 0.85
"""Dry isentropic efficiency [-] DiPippo (2016, section 5.5) assumes for geothermal turbines."""

GAS_CONSTANT = Constant(
    "WATER_GAS_CONSTANT", 461.526, "J/kg/K", "IF97 specific gas constant of water R"
)

CRITICAL_TEMPERATURE = Constant(
    "WATER_CRITICAL_TEMPERATURE", 647.096, "K", "critical temperature, end of the saturation line"
)

CRITICAL_PRESSURE = Constant("WATER_CRITICAL_PRESSURE", 22.064e6, "Pa", "critical pressure")

MINIMUM_TEMPERATURE = units.ZERO_CELSIUS
"""Lowest temperature of regions 1, 2 and 4 [K]."""

REGION_1_MAXIMUM_TEMPERATURE = 623.15
"""Upper temperature of region 1 and of the saturated states this module supports [K]."""

REGION_2_MAXIMUM_TEMPERATURE = 1073.15
"""Upper temperature of region 2 [K]."""

B23_MAXIMUM_TEMPERATURE = 863.15
"""Temperature above which region 2 extends to the maximum pressure [K]."""

MAXIMUM_PRESSURE = 100e6
"""Upper pressure of regions 1 and 2 [Pa]."""

MINIMUM_PRESSURE = 611.213
"""Saturation pressure at 273.15 K, the lowest IF97 saturation pressure [Pa]."""

MAXIMUM_SATURATION_PRESSURE = 16.529164252605e6
"""Saturation pressure at 623.15 K [Pa], the upper end of the supported saturation states."""

SATURATION_TOLERANCE = 1e-9
"""Relative pressure tolerance that keeps states computed on the saturation line in range."""

_REGION_4 = (
    0.11670521452767e4,
    -0.72421316703206e6,
    -0.17073846940092e2,
    0.12020824702470e5,
    -0.32325550322333e7,
    0.14915108613530e2,
    -0.48232657361591e4,
    0.40511340542057e6,
    -0.23855557567849,
    0.65017534844798e3,
)
"""IF97 table 34: coefficients n1 to n10 of the saturation-line equation."""

_B23 = (0.34805185628969e3, -0.11671859879975e1, 0.10192970039326e-2)
"""IF97 table 1: coefficients n1 to n3 of the B23 boundary pressure [MPa] in T [K]."""

_REGION_1 = (
    (0, -2, 0.14632971213167),
    (0, -1, -0.84548187169114),
    (0, 0, -0.37563603672040e1),
    (0, 1, 0.33855169168385e1),
    (0, 2, -0.95791963387872),
    (0, 3, 0.15772038513228),
    (0, 4, -0.16616417199501e-1),
    (0, 5, 0.81214629983568e-3),
    (1, -9, 0.28319080123804e-3),
    (1, -7, -0.60706301565874e-3),
    (1, -1, -0.18990068218419e-1),
    (1, 0, -0.32529748770505e-1),
    (1, 1, -0.21841717175414e-1),
    (1, 3, -0.52838357969930e-4),
    (2, -3, -0.47184321073267e-3),
    (2, 0, -0.30001780793026e-3),
    (2, 1, 0.47661393906987e-4),
    (2, 3, -0.44141845330846e-5),
    (2, 17, -0.72694996297594e-15),
    (3, -4, -0.31679644845054e-4),
    (3, 0, -0.28270797985312e-5),
    (3, 6, -0.85205128120103e-9),
    (4, -5, -0.22425281908000e-5),
    (4, -2, -0.65171222895601e-6),
    (4, 10, -0.14341729937924e-12),
    (5, -8, -0.40516996860117e-6),
    (8, -11, -0.12734301741641e-8),
    (8, -6, -0.17424871230634e-9),
    (21, -29, -0.68762131295531e-18),
    (23, -31, 0.14478307828521e-19),
    (29, -38, 0.26335781662795e-22),
    (30, -39, -0.11947622640071e-22),
    (31, -40, 0.18228094581404e-23),
    (32, -41, -0.93537087292458e-25),
)
"""IF97 table 2: exponents I, J and coefficients n of the region 1 Gibbs free energy."""

_REGION_2_IDEAL = (
    (0, -0.96927686500217e1),
    (1, 0.10086655968018e2),
    (-5, -0.56087911283020e-2),
    (-4, 0.71452738081455e-1),
    (-3, -0.40710498223928),
    (-2, 0.14240819171444e1),
    (-1, -0.43839511319450e1),
    (2, -0.28408632460772),
    (3, 0.21268463753307e-1),
)
"""IF97 table 10: exponents J0 and coefficients n0 of the region 2 ideal-gas part."""

_REGION_2_RESIDUAL = (
    (1, 0, -0.17731742473213e-2),
    (1, 1, -0.17834862292358e-1),
    (1, 2, -0.45996013696365e-1),
    (1, 3, -0.57581259083432e-1),
    (1, 6, -0.50325278727930e-1),
    (2, 1, -0.33032641670203e-4),
    (2, 2, -0.18948987516315e-3),
    (2, 4, -0.39392777243355e-2),
    (2, 7, -0.43797295650573e-1),
    (2, 36, -0.26674547914087e-4),
    (3, 0, 0.20481737692309e-7),
    (3, 1, 0.43870667284435e-6),
    (3, 3, -0.32277677238570e-4),
    (3, 6, -0.15033924542148e-2),
    (3, 35, -0.40668253562649e-1),
    (4, 1, -0.78847309559367e-9),
    (4, 2, 0.12790717852285e-7),
    (4, 3, 0.48225372718507e-6),
    (5, 7, 0.22922076337661e-5),
    (6, 3, -0.16714766451061e-10),
    (6, 16, -0.21171472321355e-2),
    (6, 35, -0.23895741934104e2),
    (7, 0, -0.59059564324270e-17),
    (7, 11, -0.12621808899101e-5),
    (7, 25, -0.38946842435739e-1),
    (8, 8, 0.11256211360459e-10),
    (8, 36, -0.82311340897998e1),
    (9, 13, 0.19809712802088e-7),
    (10, 4, 0.10406965210174e-18),
    (10, 10, -0.10234747095929e-12),
    (10, 14, -0.10018179379511e-8),
    (16, 29, -0.80882908646985e-10),
    (16, 50, 0.10693031879409),
    (18, 57, -0.33662250574171),
    (20, 20, 0.89185845355421e-24),
    (20, 35, 0.30629316876232e-12),
    (20, 48, -0.42002467698208e-5),
    (21, 21, -0.59056029685639e-25),
    (22, 53, 0.37826947613457e-5),
    (23, 39, -0.12768608934681e-14),
    (24, 26, 0.73087610595061e-28),
    (24, 40, 0.55414715350778e-16),
    (24, 58, -0.94369707241210e-6),
)
"""IF97 table 11: exponents I, J and coefficients n of the region 2 residual part."""


@dataclass(frozen=True)
class SaturationProperties:
    """Saturated liquid and vapour state at one pressure (SI units)."""

    pressure: float
    temperature: float
    liquid_enthalpy: float
    vapour_enthalpy: float
    liquid_entropy: float
    vapour_entropy: float

    @property
    def evaporation_enthalpy(self) -> float:
        """Return the latent heat h_g - h_f [J/kg]."""
        return self.vapour_enthalpy - self.liquid_enthalpy

    @property
    def evaporation_entropy(self) -> float:
        """Return s_g - s_f [J/kg/K]."""
        return self.vapour_entropy - self.liquid_entropy


@dataclass(frozen=True)
class Expansion:
    """Steam turbine expansion from dry saturated steam (SI units)."""

    inlet_enthalpy: float
    outlet_enthalpy: float
    outlet_quality: float
    efficiency: float


@ops.physics
def saturation_pressure(temperature: float) -> float:
    """Return the saturation pressure [Pa] of water at a temperature [K].

    Parameters
    ----------
    temperature : float
        Temperature [K], from 273.15 K to 647.096 K (the critical point).

    Returns
    -------
    float
        Saturation pressure [Pa] of liquid water (IAPWS-IF97 region 4).

    Notes
    -----
    This is the IF97 model, the one used with the steam tables of this module (separators, flash
    and turbines). ``psychrometrics.saturation_pressure`` is a different model, Hyland-Wexler
    over water and ice for moist air at atmospheric temperatures; the two differ by up to about
    3e-4 relative and both are kept because each is the standard of its field.

    IAPWS-IF97 eq. 30 with theta = T + n9 / (T - n10), A = theta^2 + n1 theta + n2,
    B = n3 theta^2 + n4 theta + n5, C = n6 theta^2 + n7 theta + n8 and
    p / 1 MPa = (2C / (-B + sqrt(B^2 - 4AC)))^4. Valid for 273.15 K <= T <= 647.096 K.
    """
    _check_range(
        "saturation_pressure",
        "temperature",
        temperature,
        "K",
        MINIMUM_TEMPERATURE,
        CRITICAL_TEMPERATURE,
    )
    n = _REGION_4
    theta = temperature + n[8] / (temperature - n[9])
    a = theta**2 + n[0] * theta + n[1]
    b = n[2] * theta**2 + n[3] * theta + n[4]
    c = n[5] * theta**2 + n[6] * theta + n[7]
    return (2 * c / (-b + ops.sqrt(b**2 - 4 * a * c))) ** 4 * units.MEGA


@ops.physics
def saturation_temperature(pressure: float) -> float:
    """Return the saturation temperature [K] of water at a pressure [Pa].

    Parameters
    ----------
    pressure : float
        Pressure [Pa], from 611.213 Pa to 22.064 MPa (the critical pressure).

    Returns
    -------
    float
        Saturation temperature [K], the inverse of ``saturation_pressure``.

    Notes
    -----
    IAPWS-IF97 eq. 31 with beta = (p / 1 MPa)^0.25, E = beta^2 + n3 beta + n6,
    F = n1 beta^2 + n4 beta + n7, G = n2 beta^2 + n5 beta + n8, D = 2G / (-F - sqrt(F^2 - 4EG))
    and T = (n10 + D - sqrt((n10 + D)^2 - 4 (n9 + n10 D))) / 2. Valid for
    611.213 Pa <= p <= 22.064 MPa, the saturation pressures of 273.15 K and the critical point.
    """
    _check_range(
        "saturation_temperature", "pressure", pressure, "Pa", MINIMUM_PRESSURE, CRITICAL_PRESSURE
    )
    n = _REGION_4
    beta = (pressure / units.MEGA) ** 0.25
    e = beta**2 + n[2] * beta + n[5]
    f = n[0] * beta**2 + n[3] * beta + n[6]
    g = n[1] * beta**2 + n[4] * beta + n[7]
    d = 2 * g / (-f - ops.sqrt(f**2 - 4 * e * g))
    return (n[9] + d - ops.sqrt((n[9] + d) ** 2 - 4 * (n[8] + n[9] * d))) / 2


@ops.physics
def liquid_enthalpy(pressure: float, temperature: float) -> float:
    """Return the specific enthalpy [J/kg] of liquid water in IF97 region 1.

    Parameters
    ----------
    pressure : float
        Absolute pressure [Pa], from the saturation pressure at ``temperature`` to 100 MPa.
    temperature : float
        Temperature [K], from 273.15 K to 623.15 K.

    Returns
    -------
    float
        Specific enthalpy h = R T tau gamma_tau [J/kg] (IF97 eq. 7 and table 3).

    Notes
    -----
    Valid for 273.15 K <= T <= 623.15 K and saturation pressure <= p <= 100 MPa.
    """
    _check_liquid("liquid_enthalpy", pressure, temperature)
    return _region_1(pressure, temperature)[0]


@ops.physics
def liquid_entropy(pressure: float, temperature: float) -> float:
    """Return the specific entropy [J/kg/K] of liquid water in IF97 region 1.

    Parameters
    ----------
    pressure : float
        Absolute pressure [Pa], from the saturation pressure at ``temperature`` to 100 MPa.
    temperature : float
        Temperature [K], from 273.15 K to 623.15 K.

    Returns
    -------
    float
        Specific entropy s = R (tau gamma_tau - gamma) [J/kg/K] (IF97 eq. 7 and table 3).

    Notes
    -----
    Valid for 273.15 K <= T <= 623.15 K and saturation pressure <= p <= 100 MPa.
    """
    _check_liquid("liquid_entropy", pressure, temperature)
    return _region_1(pressure, temperature)[1]


@ops.physics
def vapour_enthalpy(pressure: float, temperature: float) -> float:
    """Return the specific enthalpy [J/kg] of steam in IF97 region 2.

    Parameters
    ----------
    pressure : float
        Absolute pressure [Pa], above 0 and up to the limit given below.
    temperature : float
        Temperature [K], from 273.15 K to 1073.15 K.

    Returns
    -------
    float
        Specific enthalpy h = R T tau gamma_tau [J/kg] (IF97 eqs. 15 to 17 and table 12).

    Notes
    -----
    Valid for 0 < p <= saturation pressure at 273.15 K <= T <= 623.15 K, 0 < p <= B23 pressure
    up to 863.15 K and 0 < p <= 100 MPa up to 1073.15 K.
    """
    _check_vapour("vapour_enthalpy", pressure, temperature)
    return _region_2(pressure, temperature)[0]


@ops.physics
def vapour_entropy(pressure: float, temperature: float) -> float:
    """Return the specific entropy [J/kg/K] of steam in IF97 region 2.

    Parameters
    ----------
    pressure : float
        Absolute pressure [Pa], above 0 and up to the limit given below.
    temperature : float
        Temperature [K], from 273.15 K to 1073.15 K.

    Returns
    -------
    float
        Specific entropy s = R (tau gamma_tau - gamma) [J/kg/K] (IF97 eqs. 15 to 17 and table 12).

    Notes
    -----
    Valid for 0 < p <= saturation pressure at 273.15 K <= T <= 623.15 K, 0 < p <= B23 pressure
    up to 863.15 K and 0 < p <= 100 MPa up to 1073.15 K.
    """
    _check_vapour("vapour_entropy", pressure, temperature)
    return _region_2(pressure, temperature)[1]


@ops.physics
def b23_pressure(temperature: float) -> float:
    """Return the region 2/3 boundary pressure [Pa] (IF97 eq. 5, 623.15 K to 863.15 K).

    Parameters
    ----------
    temperature : float
        Temperature [K], from 623.15 K to 863.15 K.

    Returns
    -------
    float
        Boundary pressure [Pa], p / 1 MPa = n1 + n2 T + n3 T^2 with the coefficients of table 1.

    Notes
    -----
    Validity: temperature from 623.15 K to 863.15 K; other values raise PhysicsError. No
    division occurs.
    Source: IAPWS (2007), Revised Release on the IAPWS Industrial Formulation 1997
    (IAPWS-R7-97(2012)), eq. 5 and table 1.
    """
    _check_range(
        "b23_pressure",
        "temperature",
        temperature,
        "K",
        REGION_1_MAXIMUM_TEMPERATURE,
        B23_MAXIMUM_TEMPERATURE,
    )
    n = _B23
    return (n[0] + n[1] * temperature + n[2] * temperature**2) * units.MEGA


@ops.physics
def saturation_properties(pressure: float) -> SaturationProperties:
    """Return saturated liquid and vapour enthalpy and entropy at a pressure [Pa].

    Parameters
    ----------
    pressure : float
        Saturation pressure [Pa], from 611.213 Pa to 16.529 MPa.

    Returns
    -------
    SaturationProperties
        ``pressure`` [Pa], ``temperature`` [K], ``liquid_enthalpy`` and ``vapour_enthalpy``
        [J/kg], ``liquid_entropy`` and ``vapour_entropy`` [J/kg/K]; ``evaporation_enthalpy``
        [J/kg] and ``evaporation_entropy`` [J/kg/K] are their differences.

    Notes
    -----
    The saturation temperature comes from IF97 eq. 31; the liquid from region 1 and the vapour
    from region 2 at that temperature. Valid for 611.213 Pa <= p <= 16.529 MPa, the saturation
    pressures of 273.15 K and 623.15 K; region 3 above is not implemented.
    """
    _check_range(
        "saturation_properties",
        "pressure",
        pressure,
        "Pa",
        MINIMUM_PRESSURE,
        MAXIMUM_SATURATION_PRESSURE,
    )
    temperature = saturation_temperature(pressure)
    liquid = _region_1(pressure, temperature)
    vapour = _region_2(pressure, temperature)
    return SaturationProperties(pressure, temperature, liquid[0], vapour[0], liquid[1], vapour[1])


@ops.physics
def flash_fraction(enthalpy: float, pressure: float) -> float:
    """Return the steam mass fraction [-] after isenthalpic flashing to a pressure [Pa].

    Parameters
    ----------
    enthalpy : float
        Specific enthalpy of the fluid before flashing [J/kg].
    pressure : float
        Flash pressure [Pa], from 611.213 Pa to 16.529 MPa.

    Returns
    -------
    float
        Steam mass fraction x [-] in [0, 1).

    Notes
    -----
    x = (h - h_f) / h_fg at the flash pressure, zero for subcooled liquid (h <= h_f).
    An enthalpy at or above saturated vapour raises ``PhysicsError``: the fluid does not
    separate into two phases. Reference: DiPippo, R. (2016), Geothermal Power Plants, 4th ed.,
    Butterworth-Heinemann, section 5.2 (single-flash plants).
    """
    saturation = saturation_properties(pressure)
    ops.check(
        enthalpy < saturation.vapour_enthalpy,
        PhysicsError,
        "flash_fraction: enthalpy = {enthalpy} J/kg; expected below the saturated vapour "
        "enthalpy {vapour_enthalpy} J/kg at {pressure} Pa",
        enthalpy=enthalpy,
        vapour_enthalpy=saturation.vapour_enthalpy,
        pressure=pressure,
    )
    return ops.maximum(
        0.0, (enthalpy - saturation.liquid_enthalpy) / saturation.evaporation_enthalpy
    )


@dataclass(frozen=True)
class FlashState:
    """Result of a flash: the split of the mass flow and the saturation temperature."""

    steam_fraction: float
    steam_flow: float
    liquid_flow: float
    liquid_temperature: float
    saturation_temperature: float


@ops.physics
def flash_state(
    mass_flow: float, inlet_temperature: float, inlet_pressure: float, flash_pressure: float
) -> FlashState:
    """Return the single-flash split of a liquid into saturated steam and brine.

    Parameters
    ----------
    mass_flow : float
        Inlet mass flow [kg/s], nonnegative.
    inlet_temperature : float
        Temperature of the liquid before it flashes [K].
    inlet_pressure : float
        Pressure of the liquid [Pa]; when below the saturation pressure of the inlet
        temperature the enthalpy is taken at that saturation pressure.
    flash_pressure : float
        Separator pressure [Pa], from 611.213 Pa to 16.529 MPa, at most the inlet pressure.

    Returns
    -------
    FlashState
        ``steam_fraction`` x [-]; ``steam_flow`` x m and ``liquid_flow`` m - x m [kg/s];
        ``liquid_temperature`` [K], the saturation temperature when flashing, else the inlet
        temperature; ``saturation_temperature`` [K] at the flash pressure.

    Notes
    -----
    The inlet enthalpy is the IF97 region 1 liquid enthalpy; the fraction follows
    ``flash_fraction`` (DiPippo, R. (2016), Geothermal Power Plants, 4th ed., section 5.2).
    """
    liquid_pressure = ops.maximum(inlet_pressure, saturation_pressure(inlet_temperature))
    enthalpy = liquid_enthalpy(liquid_pressure, inlet_temperature)
    fraction = flash_fraction(enthalpy, flash_pressure)
    saturation = saturation_properties(flash_pressure)
    steam_flow = fraction * mass_flow
    return FlashState(
        steam_fraction=fraction,
        steam_flow=steam_flow,
        liquid_flow=mass_flow - steam_flow,
        liquid_temperature=ops.where(fraction > 0, saturation.temperature, inlet_temperature),
        saturation_temperature=saturation.temperature,
    )


@dataclass(frozen=True)
class TurbineBalance:
    """Powers of a condensing steam turbine with generator (W)."""

    gross_power: float
    electricity_generated: float
    condenser_duty: float
    heat_loss: float


@ops.physics
def turbine_balance(
    mass_flow: float,
    inlet_enthalpy: float,
    outlet_enthalpy: float,
    condensate_enthalpy: float,
    generator_efficiency: float,
) -> TurbineBalance:
    """Return the enthalpy balance of a condensing turbine, generator and condenser.

    Parameters
    ----------
    mass_flow : float
        Steam mass flow [kg/s].
    inlet_enthalpy, outlet_enthalpy : float
        Specific enthalpy of the steam entering and of the exhaust [J/kg].
    condensate_enthalpy : float
        Saturated liquid enthalpy at the condenser pressure [J/kg].
    generator_efficiency : float
        Generator efficiency [-].

    Returns
    -------
    TurbineBalance
        ``gross_power`` m (h_in - h_out); ``electricity_generated`` the gross power times the
        generator efficiency; ``condenser_duty`` m (h_out - h_f); ``heat_loss`` the condenser
        duty plus the generator loss [W].

    Notes
    -----
    Steady-flow first law of the turbine and the condenser (DiPippo, R. (2016), Geothermal
    Power Plants, 4th ed., section 5.5): m h_in = electricity + heat_loss + m h_f.

    Validity: mass_flow nonnegative; inlet_enthalpy >= outlet_enthalpy >= condensate_enthalpy;
    generator_efficiency in (0, 1]; no division occurs.
    """
    gross_power = mass_flow * (inlet_enthalpy - outlet_enthalpy)
    electricity_generated = gross_power * generator_efficiency
    condenser_duty = mass_flow * (outlet_enthalpy - condensate_enthalpy)
    return TurbineBalance(
        gross_power=gross_power,
        electricity_generated=electricity_generated,
        condenser_duty=condenser_duty,
        heat_loss=condenser_duty + gross_power - electricity_generated,
    )


@ops.physics
def baumann_expansion(
    inlet_pressure: float,
    outlet_pressure: float,
    dry_efficiency: float,
    baumann_factor: float,
) -> Expansion:
    """Return the expansion of dry saturated steam into the wet region with the Baumann rule.

    Parameters
    ----------
    inlet_pressure, outlet_pressure : float
        Pressures [Pa] of the dry saturated inlet steam and of the exhaust, inlet > outlet.
    dry_efficiency : float
        Isentropic efficiency of the turbine expanding dry steam, in (0, 1] [-].
    baumann_factor : float
        Baumann factor a >= 0 [-]: the efficiency falls by a percent per percent of mean
        moisture; a = 1 is the classical Baumann rule.

    Returns
    -------
    Expansion
        ``inlet_enthalpy`` and ``outlet_enthalpy`` [J/kg];
        ``outlet_quality`` [-], the steam mass fraction of the exhaust; ``efficiency`` [-], the
        wet isentropic efficiency (h_in - h_out) / (h_in - h_s).

    Notes
    -----
    The isentropic exhaust state follows from s_in = s_g(p_in): x_s = (s_in - s_f) / s_fg and
    h_s = h_f + x_s h_fg at the outlet pressure. The wet efficiency is
    eta = eta_d (1 - a (1 - (x_in + x_out) / 2)) with x_in = 1, and h_out = h_in - eta (h_in -
    h_s). Since x_out = (h_out - h_f) / h_fg depends on eta, the linear system is solved in
    closed form: x_out = (h_in - h_f - eta_d dh_s (1 - a / 2)) / (h_fg + a eta_d dh_s / 2). For
    a = 1 this is DiPippo's eq. 5.13 with A = eta_d dh_s / 2. A dry or superheated exhaust
    (x_out >= 1) is outside this wet-expansion model and raises ``PhysicsError``.
    Reference: Baumann, K. (1921), Some recent developments in large steam turbine practice,
    J. Inst. Electr. Eng. 59, 565-623; DiPippo, R. (2016), Geothermal Power Plants, 4th ed.,
    section 5.5.
    """
    ops.check(
        ops.logical_and(
            ops.logical_and(dry_efficiency > 0, dry_efficiency <= 1),
            ops.logical_not(baumann_factor < 0),
        ),
        PhysicsError,
        "baumann_expansion: dry_efficiency = {dry_efficiency}, baumann_factor = "
        "{baumann_factor}; expected 0 < dry_efficiency <= 1 and baumann_factor >= 0",
        dry_efficiency=dry_efficiency,
        baumann_factor=baumann_factor,
    )
    ops.check(
        ops.logical_not(outlet_pressure >= inlet_pressure),
        PhysicsError,
        "baumann_expansion: outlet_pressure = {outlet_pressure} Pa; expected below "
        "inlet_pressure = {inlet_pressure} Pa",
        outlet_pressure=outlet_pressure,
        inlet_pressure=inlet_pressure,
    )
    inlet, outlet = saturation_properties(inlet_pressure), saturation_properties(outlet_pressure)
    h_in = inlet.vapour_enthalpy
    isentropic_quality = (inlet.vapour_entropy - outlet.liquid_entropy) / outlet.evaporation_entropy
    h_s = outlet.liquid_enthalpy + isentropic_quality * outlet.evaporation_enthalpy
    drop = dry_efficiency * (h_in - h_s)
    quality = (h_in - outlet.liquid_enthalpy - drop * (1 - baumann_factor / 2)) / (
        outlet.evaporation_enthalpy + baumann_factor * drop / 2
    )
    ops.check(
        ops.logical_not(quality >= 1),
        PhysicsError,
        "baumann_expansion: exhaust quality = {quality}; expected a wet exhaust below 1",
        quality=quality,
    )
    h_out = outlet.liquid_enthalpy + quality * outlet.evaporation_enthalpy
    return Expansion(h_in, h_out, quality, (h_in - h_out) / (h_in - h_s))


def _region_1(pressure, temperature):
    """Return (h [J/kg], s [J/kg/K]) from the IF97 region 1 Gibbs free energy."""
    pi = pressure / 16.53e6
    tau = 1386 / temperature
    gamma = gamma_tau = 0.0
    for i, j, n in _REGION_1:
        gamma += n * (7.1 - pi) ** i * (tau - 1.222) ** j
        gamma_tau += n * (7.1 - pi) ** i * j * (tau - 1.222) ** (j - 1)
    rt = GAS_CONSTANT * temperature
    return rt * tau * gamma_tau, GAS_CONSTANT * (tau * gamma_tau - gamma)


def _region_2(pressure, temperature):
    """Return (h [J/kg], s [J/kg/K]) from the IF97 region 2 Gibbs free energy."""
    pi = pressure / units.MEGA
    tau = 540 / temperature
    gamma = ops.log(pi)
    gamma_tau = 0.0
    for j, n in _REGION_2_IDEAL:
        gamma += n * tau**j
        gamma_tau += n * j * tau ** (j - 1)
    for i, j, n in _REGION_2_RESIDUAL:
        gamma += n * pi**i * (tau - 0.5) ** j
        gamma_tau += n * pi**i * j * (tau - 0.5) ** (j - 1)
    rt = GAS_CONSTANT * temperature
    return rt * tau * gamma_tau, GAS_CONSTANT * (tau * gamma_tau - gamma)


def _check_range(function, name, value, unit, lower, upper):
    """Raise ``PhysicsError`` unless lower <= value <= upper (NaN fails)."""
    ops.check(
        ops.logical_and(lower <= value, value <= upper),
        PhysicsError,
        "{function}: {name} = {value} {unit}; expected {lower} {unit} to {upper} {unit}",
        function=function,
        name=name,
        value=value,
        unit=unit,
        lower=lower,
        upper=upper,
    )


def _check_liquid(function, pressure, temperature):
    """Raise ``PhysicsError`` outside IF97 region 1."""
    _check_range(
        function, "temperature", temperature, "K", MINIMUM_TEMPERATURE, REGION_1_MAXIMUM_TEMPERATURE
    )
    lower = saturation_pressure(temperature) * (1 - SATURATION_TOLERANCE)
    _check_range(function, "pressure", pressure, "Pa", lower, MAXIMUM_PRESSURE)


def _check_vapour(function, pressure, temperature):
    """Raise ``PhysicsError`` outside IF97 region 2."""
    _check_range(
        function, "temperature", temperature, "K", MINIMUM_TEMPERATURE, REGION_2_MAXIMUM_TEMPERATURE
    )
    upper = ops.where(
        temperature <= REGION_1_MAXIMUM_TEMPERATURE,
        saturation_pressure(temperature) * (1 + SATURATION_TOLERANCE),
        ops.where(
            temperature <= B23_MAXIMUM_TEMPERATURE,
            b23_pressure(temperature),
            MAXIMUM_PRESSURE,
        ),
    )
    ops.check(
        ops.logical_and(pressure > 0, pressure <= upper),
        PhysicsError,
        "{function}: pressure = {pressure} Pa; expected 0 Pa < pressure <= {upper} Pa in "
        "region 2 at {temperature} K",
        function=function,
        pressure=pressure,
        upper=upper,
        temperature=temperature,
    )


@ops.physics
def lorenz_efficiency(
    hot_temperature: float, cold_temperature: float, condensing_temperature: float
):
    """Return the reversible efficiency of a sensible heat glide rejected at a temperature.

    Parameters
    ----------
    hot_temperature, cold_temperature : float
        Working-fluid temperatures T_a and T_b [K] at the start and end of the heat addition,
        positive and different.
    condensing_temperature : float
        Heat rejection temperature T_c [K].

    Returns
    -------
    float
        ``1 - T_c ln(T_a / T_b) / (T_a - T_b)`` [-], that is ``1 - T_c / T_lm`` with the
        logarithmic mean ``T_lm`` of ``refrigeration.log_mean_temperature``.

    Notes
    -----
    Lorenz (1894); DiPippo (2007). The expression is not written with
    ``refrigeration.log_mean_temperature``: that function checks its arguments and returns the
    inlet for equal temperatures, while this one keeps the retained floating-point order.
    """
    return 1 - condensing_temperature * ops.log(hot_temperature / cold_temperature) / (
        hot_temperature - cold_temperature
    )


@dataclass(frozen=True)
class CycleDesign:
    """Operating point of an organic Rankine cycle on a brine stream."""

    condensing_temperature: float
    outlet_temperature: float
    cycle_efficiency: float
    processed_share: float
    is_capped: bool


@ops.physics
def cycle_design(
    brine_temperature: float,
    brine_mass_flow: float,
    brine_heat_capacity: float,
    ambient_temperature: float,
    condenser_approach: float,
    pinch: float,
    minimum_outlet_temperature: float,
    carnot_fraction: float,
    capacity: float,
) -> CycleDesign:
    """Return the design point of an air-cooled binary cycle fed by brine.

    Parameters
    ----------
    brine_temperature : float
        Brine inlet temperature T_in [K].
    brine_mass_flow : float
        Brine mass flow [kg/s], nonnegative.
    brine_heat_capacity : float
        Brine specific heat capacity [J/kg/K].
    ambient_temperature, condenser_approach : float
        Air temperature [K] and condenser approach [K].
    pinch : float
        Pinch between brine and working fluid [K], nonnegative.
    minimum_outlet_temperature : float
        Lowest allowed brine outlet temperature [K].
    carnot_fraction : float
        Second-law fraction of the Lorenz efficiency [-].
    capacity : float
        Gross power limit [W], positive.

    Returns
    -------
    CycleDesign
        ``condensing_temperature`` T_c = T_amb + approach; ``outlet_temperature`` T_out =
        max(T_min, T_c + pinch) [K]; ``cycle_efficiency`` fraction * Lorenz efficiency between
        T_in - pinch and T_out - pinch [-]; ``processed_share`` of the brine, capacity over the
        uncapped gross power when that exceeds the capacity, else one [-]; ``is_capped``.
        The efficiency, the share and the flag are zero (false) when T_in <= T_out.

    Notes
    -----
    Uncapped gross power is ``eta m cp (T_in - T_out)``. Part-load degradation is not modelled.
    DiPippo (2016), chapter 8; DiPippo (2004), Second Law assessment of binary plants,
    Geothermics 33, 565-586, for second-law fractions of about 0.3 to 0.6.
    """
    condensing_temperature = ambient_temperature + condenser_approach
    outlet_temperature = ops.maximum(minimum_outlet_temperature, condensing_temperature + pinch)
    running = brine_temperature > outlet_temperature
    reversible = lorenz_efficiency(
        brine_temperature - pinch, outlet_temperature - pinch, condensing_temperature
    )
    efficiency = carnot_fraction * reversible
    uncapped = (
        efficiency
        * brine_mass_flow
        * brine_heat_capacity
        * (brine_temperature - outlet_temperature)
    )
    is_capped = uncapped > capacity
    share = ops.where(is_capped, capacity / uncapped, 1.0)
    return CycleDesign(
        condensing_temperature=condensing_temperature,
        outlet_temperature=outlet_temperature,
        cycle_efficiency=ops.where(running, efficiency, 0.0),
        processed_share=ops.where(running, share, 0.0),
        is_capped=ops.where(running, is_capped, False),
    )


@dataclass(frozen=True)
class PlantBalance:
    """Powers [W] and efficiency of a binary plant."""

    gross_power: float
    parasitic_power: float
    electricity_generated: float
    condenser_duty: float
    heat_loss: float
    thermal_efficiency: float


@ops.physics
def plant_balance(
    heat_input: float, cycle_efficiency: float, parasitic_fraction: float
) -> PlantBalance:
    """Return the energy balance of a binary plant from its heat input.

    Parameters
    ----------
    heat_input : float
        Heat taken from the brine Q [W].
    cycle_efficiency : float
        Gross cycle efficiency [-].
    parasitic_fraction : float
        Share of the gross power used by feed pump, fans and controls [-], in [0, 1).

    Returns
    -------
    PlantBalance
        ``gross_power`` eta Q; ``parasitic_power`` f W; ``electricity_generated`` W - parasitic;
        ``condenser_duty`` Q - W; ``heat_loss`` condenser duty plus parasitic power [W];
        ``thermal_efficiency`` net power over Q [-], ``None`` without heat input.

    Notes
    -----
    First law: Q = gross + condenser duty = net + heat_loss (DiPippo 2016, chapter 8). The
    parasitic power ends as heat in the air.

    Validity: heat_input nonnegative, cycle_efficiency in [0, 1], parasitic_fraction in [0, 1);
    ``thermal_efficiency`` is ``None`` for heat_input <= 0, so no division by zero occurs.
    """
    gross_power = cycle_efficiency * heat_input
    parasitic_power = parasitic_fraction * gross_power
    electricity_generated = gross_power - parasitic_power
    condenser_duty = heat_input - gross_power
    return PlantBalance(
        gross_power=gross_power,
        parasitic_power=parasitic_power,
        electricity_generated=electricity_generated,
        condenser_duty=condenser_duty,
        heat_loss=condenser_duty + parasitic_power,
        thermal_efficiency=ops.where(heat_input > 0, electricity_generated / heat_input, None),
    )
