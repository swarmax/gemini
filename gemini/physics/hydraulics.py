"""Pipe hydraulics: Darcy–Weisbach with Swamee–Jain, Beggs–Brill, path marching, radial inflow.

Inclinations are measured from horizontal [rad], positive when descending in surface-to-bottom
order, as built by :func:`geometry.build_path`. This module also composes the path marcher
with the corrosion and erosion correlations for the wells.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import reduce
from typing import TYPE_CHECKING, Literal

from gemini import ops, units
from gemini.errors import PhysicsError, ValidationError
from gemini.ops import Constant

from . import corrosion, erosion
from . import fluid as fluid_physics
from . import gas, geometry, heat_transfer
from .constants import G_FT, MIN_PATH_PRESSURE, VALVE_REFERENCE_DENSITY, G

if TYPE_CHECKING:
    from gemini.types.flows import Stream
    from gemini.types.fluid import Fluid

_HORIZONTAL_HOLDUP = {
    "segregated": (0.98, 0.4846, 0.0868),
    "intermittent": (0.845, 0.5351, 0.0173),
    "distributed": (1.065, 0.5824, 0.0609),
}
"""Beggs–Brill horizontal holdup ``a * lambda**b / Fr**c`` per flow regime."""

_SEGREGATED, _TRANSITION, _INTERMITTENT, _DISTRIBUTED, _OUTSIDE_MAP = 0, 1, 2, 3, -1
"""Codes of the Beggs–Brill flow regimes, and of a pair outside the regime map."""

_DOWNHILL = (4.7, -0.3692, 0.1244, -0.5056)
_SEGREGATED_UPHILL = (0.011, -3.768, 3.539, -1.614)
_INTERMITTENT_UPHILL = (2.96, 0.305, -0.4473, 0.0978)


PIPE_LAMINAR_REYNOLDS = Constant(
    "PIPE_LAMINAR_REYNOLDS",
    2300,
    "-",
    "Reynolds number up to which pipe flow is taken as laminar (Hagen–Poiseuille)",
)
PIPE_TURBULENT_REYNOLDS = Constant(
    "PIPE_TURBULENT_REYNOLDS",
    4000,
    "-",
    "Reynolds number from which pipe flow is taken as turbulent (Swamee–Jain)",
)


@ops.physics
def reynolds_number(velocity: float, density: float, diameter: float, viscosity: float) -> float:
    """Return the Reynolds number [-] of a flow in a pipe, ``Re = u rho D / mu``.

    Parameters
    ----------
    velocity : float
        Mean velocity [m/s]; pass its magnitude for a signed flow.
    density : float
        Density [kg/m3].
    diameter : float
        Internal diameter [m].
    viscosity : float
        Dynamic viscosity [Pa s], nonzero.

    Returns
    -------
    float
        Reynolds number [-], zero at zero velocity.

    Notes
    -----
    Definition of the ratio of inertial to viscous forces. Any consistent unit system gives
    the same value. Reference: White, Fluid Mechanics, 8th ed., section 6.1.
    """
    return velocity * density * diameter / viscosity


@ops.physics
def darcy_weisbach_dp(
    velocity: float,
    rho: float,
    inclination: float,
    mu: float,
    diameter: float,
    roughness: float,
    length: float,
) -> tuple[float, float]:
    """Return the signed friction and gravity pressure drops [Pa] of one pipe interval.

    ``dp_f = f (rho L / D) u |u| / 2`` with ``Re = |u| rho D / mu`` and the Swamee-Jain factor
    ``f = 0.25 / log10(eps / (3.7 D) + 5.74 / Re**0.9)**2``; ``dp_g = rho g L sin(theta)``.

    Parameters
    ----------
    velocity, rho, mu : float
        Signed velocity [m/s], density [kg/m3], dynamic viscosity [Pa s].
    inclination : float
        Pipe angle from horizontal [rad], positive when descending in surface-to-bottom order.
    diameter, roughness, length : float
        Internal diameter, absolute roughness and interval length [m].

    Returns
    -------
    tuple of float
        Signed friction drop and gravity drop [Pa]; zero velocity gives zero friction.

    Notes
    -----
    Valid for single-phase turbulent flow, ``5e3 <= Re <= 1e8`` and ``1e-6 <= eps / D <= 1e-2``
    (the range of the Swamee-Jain fit); outside it, and for laminar flow, the friction is
    extrapolated. Reference: Swamee and Jain (1976), Explicit Equations for Pipe-Flow
    Problems, J. Hydraul. Div. ASCE 102(5), 657-664, combined with the Darcy-Weisbach
    equation and the hydrostatic balance; retained GEMINI formulation.
    """
    reynolds = reynolds_number(ops.abs(velocity), rho, diameter, mu)
    friction_factor = 0.25 / (ops.log10((roughness / (3.7 * diameter)) + 5.74 / reynolds**0.9)) ** 2
    gravity = hydrostatic_dp(rho, length, ops.sin(inclination))
    friction = friction_factor * rho * length / diameter * (ops.abs(velocity) * velocity) / 2
    return ops.where(velocity == 0, 0.0, friction), gravity


@ops.physics
def pipe_friction_drop(
    velocity: float,
    rho: float,
    mu: float,
    diameter: float,
    roughness: float,
    length: float,
) -> float:
    """Return the friction pressure drop [Pa] of a liquid in a straight pipe, any regime.

    Laminar (``Re <= 2300``): ``dp = 32 mu L u / D^2``, that is ``f = 64 / Re``. Turbulent
    (``Re >= 4000``): Darcy-Weisbach with the Swamee-Jain factor, see ``darcy_weisbach_dp``. In
    between, ``dp`` is interpolated linearly in ``Re`` between the laminar drop at 2300 and the
    turbulent drop at 4000.

    Parameters
    ----------
    velocity : float
        Mean velocity [m/s], nonnegative.
    rho, mu : float
        Liquid density [kg/m3] and dynamic viscosity [Pa s].
    diameter, roughness, length : float
        Internal diameter, absolute roughness and length of the pipe [m].

    Returns
    -------
    float
        Friction pressure drop [Pa], zero at zero velocity.

    Notes
    -----
    Valid for single-phase liquid flow with the Swamee-Jain range of ``darcy_weisbach_dp``. The
    bridge is a continuous interpolation without physical claim for the intermittent transition
    regime. References: Hagen-Poiseuille (White, Fluid Mechanics, 8th ed., section 6.4) and
    Swamee and Jain (1976), J. Hydraul. Div. ASCE 102; the bridge is a retained GEMINI
    formulation.
    """
    velocity_per_reynolds = mu / (rho * diameter)
    reynolds = reynolds_number(velocity, rho, diameter, mu)
    laminar_limit = _laminar_drop(
        PIPE_LAMINAR_REYNOLDS * velocity_per_reynolds, mu, diameter, length
    )
    turbulent_limit = _turbulent_drop(
        PIPE_TURBULENT_REYNOLDS * velocity_per_reynolds, rho, mu, diameter, roughness, length
    )
    weight = (reynolds - PIPE_LAMINAR_REYNOLDS) / (PIPE_TURBULENT_REYNOLDS - PIPE_LAMINAR_REYNOLDS)
    return ops.where(
        reynolds <= PIPE_LAMINAR_REYNOLDS,
        _laminar_drop(velocity, mu, diameter, length),
        ops.where(
            reynolds >= PIPE_TURBULENT_REYNOLDS,
            _turbulent_drop(velocity, rho, mu, diameter, roughness, length),
            laminar_limit + weight * (turbulent_limit - laminar_limit),
        ),
    )


def _laminar_drop(velocity, mu, diameter, length):
    """Return the Hagen-Poiseuille drop ``32 mu L u / D^2`` [Pa]."""
    return 32 * mu * length * velocity / diameter**2


def _turbulent_drop(velocity, rho, mu, diameter, roughness, length):
    """Return the friction drop [Pa] of ``darcy_weisbach_dp`` for a horizontal pipe."""
    return darcy_weisbach_dp(velocity, rho, 0.0, mu, diameter, roughness, length)[0]


@ops.physics
def pipe_conductance(heat_transfer_coefficient: float, diameter: float, length: float) -> float:
    """Return the conductance ``UA`` [W/K] of a pipe wall, ``U pi D L``.

    Parameters
    ----------
    heat_transfer_coefficient : float
        Overall heat transfer coefficient [W/m2/K] referred to the inner wall area.
    diameter, length : float
        Internal diameter and length [m].

    Returns
    -------
    float
        Conductance [W/K].

    Notes
    -----
    Valid for any real inputs; the convention of the well path model, with the inner wall
    area ``geometry.lateral_area``. Reference: Incropera et al., Fundamentals of Heat and Mass
    Transfer, overall heat transfer coefficient ``UA``.
    """
    return heat_transfer_coefficient * geometry.lateral_area(diameter, length)


@ops.physics
def valve_flow_coefficient(
    rated: float, opening: float, rangeability: float, equal_percentage: bool
) -> float:
    """Return the effective flow coefficient of a control valve at an opening.

    ``Phi_0 = 1 / R``; linear ``Phi = Phi_0 + (1 - Phi_0) h``; equal percentage ``Phi = R^(h - 1)``;
    ``Kv_eff = rated Phi``, zero at ``h = 0`` (seated valve).

    Parameters
    ----------
    rated : float
        Flow coefficient at full opening, in any unit; the result has its unit.
    opening : float
        Relative opening ``h`` [-], in [0, 1].
    rangeability : float
        Inherent rangeability ``R`` [-], above 1.
    equal_percentage : bool
        True for the equal-percentage characteristic, false for the linear one.

    Returns
    -------
    float
        Effective flow coefficient, in the unit of ``rated``.

    Notes
    -----
    Theoretical inherent characteristics of IEC 60534-2-4 with a seated closure at zero opening;
    a real valve deviates below ``Phi_0``.
    """
    floor = 1 / rangeability
    linear = rated * (floor + (1 - floor) * opening)
    percentage = rated * rangeability ** (opening - 1)
    return ops.where(opening == 0, 0.0, ops.where(equal_percentage, percentage, linear))


@ops.physics
def affine_correction(pressure: float, slope: float, offset: float) -> float:
    """Return a pressure with the affine calibration correction, ``a p + b``.

    Parameters
    ----------
    pressure : float
        Calculated pressure [Pa].
    slope : float
        Dimensionless factor ``a`` [-].
    offset : float
        Additive correction ``b`` [Pa].

    Returns
    -------
    float
        Corrected pressure [Pa].

    Notes
    -----
    Calibration convention of the GEMINI well models, fitted to measured pressures; no
    published source.

    Validity: Valid for any real pressure and offset; slope is positive in practice. No division
    occurs.
    """
    return slope * pressure + offset


@ops.physics
def productivity_pressure(reservoir_pressure: float, flow: float, productivity: float) -> float:
    """Return the bottomhole pressure [Pa] of a producer on a linear IPR, ``p - q / PI``.

    Parameters
    ----------
    reservoir_pressure : float
        Reservoir pressure [Pa].
    flow : float
        Volume flow into the well [m3/s].
    productivity : float
        Productivity index ``PI`` [m3/s/Pa], nonzero.

    Returns
    -------
    float
        Flowing bottomhole pressure [Pa].

    Notes
    -----
    Linear inflow performance of a single-phase liquid well above its bubble point. Reference:
    Economides et al., Petroleum Production Systems, 2nd ed., chapter 2.
    """
    return reservoir_pressure - flow / productivity


@ops.physics
def injectivity_pressure(reservoir_pressure: float, flow: float, injectivity: float) -> float:
    """Return the bottomhole pressure [Pa] of an injector on a linear law, ``p + q / II``.

    Parameters
    ----------
    reservoir_pressure : float
        Reservoir pressure [Pa].
    flow : float
        Volume flow out of the well [m3/s], nonnegative.
    injectivity : float
        Injectivity index ``II`` [m3/s/Pa], nonzero.

    Returns
    -------
    float
        Bottomhole pressure [Pa] the injection requires.

    Notes
    -----
    Mirror of ``productivity_pressure`` for a single-phase liquid; the injection pressure stays
    below the fracturing pressure. Reference: Economides et al., Petroleum Production Systems.
    """
    return reservoir_pressure + flow / injectivity


@ops.physics
def productivity_index(flow: float, reservoir_pressure: float, bottomhole_pressure: float) -> float:
    """Return the productivity index [m3/s/Pa] of one measurement, ``q / (p_res - p_bh)``.

    Parameters
    ----------
    flow : float
        Volume flow into the well [m3/s].
    reservoir_pressure, bottomhole_pressure : float
        Pressures [Pa]; they must differ.

    Returns
    -------
    float
        Productivity index [m3/s/Pa].

    Notes
    -----
    Inverse of ``productivity_pressure``. Reference: Economides et al., Petroleum Production
    Systems.

    Validity: reservoir_pressure and bottomhole_pressure must differ (the code divides by the
    difference); the index is positive for a producer with bottomhole_pressure below
    reservoir_pressure. A constant index holds for single-phase, pseudo-steady Darcy flow.
    """
    return flow / (reservoir_pressure - bottomhole_pressure)


@ops.physics
def injectivity_index(flow: float, reservoir_pressure: float, bottomhole_pressure: float) -> float:
    """Return the injectivity index [m3/s/Pa] of one measurement, ``q / (p_bh - p_res)``.

    Parameters
    ----------
    flow : float
        Volume flow out of the well [m3/s].
    reservoir_pressure, bottomhole_pressure : float
        Pressures [Pa]; they must differ.

    Returns
    -------
    float
        Injectivity index [m3/s/Pa].

    Notes
    -----
    Inverse of ``injectivity_pressure``. Reference: Economides et al., Petroleum Production
    Systems.

    Validity: reservoir_pressure and bottomhole_pressure must differ (the code divides by the
    difference); the index is positive for an injector with bottomhole_pressure above
    reservoir_pressure. A constant index holds for single-phase, pseudo-steady Darcy flow.
    """
    return flow / (bottomhole_pressure - reservoir_pressure)


@ops.physics
def beggs_brill_dp(
    us_g: float,
    us_l: float,
    rho_g: float,
    rho_l: float,
    inclination: float,
    mu_g: float,
    mu_l: float,
    sigma: float,
    diameter: float,
    roughness: float,
    length: float,
) -> tuple[float, float]:
    """Return the two-phase friction and gravity pressure drops [Pa] of one pipe interval.

    ``dp_f = f_n (f_tp / f_n) (rho_n u_m |u_m| / 2) (L / D)`` with the no-slip density
    ``rho_n``, mixture velocity ``u_m = us_g + us_l`` and Reynolds number
    ``Re = u_m rho_n D / mu_n``, the explicit Colebrook-type friction factor ``f_n`` of the
    no-slip mixture and the Beggs-Brill multiplier ``f_tp / f_n = exp(s)``;
    ``dp_g = rho_s g L sin(theta)`` with the slip density ``rho_s = H rho_l + (1 - H) rho_g``
    of the liquid holdup ``H``.

    Parameters
    ----------
    us_g, us_l : float
        Gas and liquid superficial velocities [m/s]; the liquid velocity must be nonzero.
    rho_g, rho_l : float
        Phase densities [kg/m3].
    inclination : float
        Pipe angle from horizontal [rad], positive when descending in surface-to-bottom order.
    mu_g, mu_l : float
        Phase dynamic viscosities [Pa s].
    sigma : float
        Gas/liquid surface tension [N/m].
    diameter, roughness, length : float
        Pipe internal diameter, absolute roughness and interval length [m].

    Returns
    -------
    tuple of float
        Friction and gravity pressure drops [Pa].

    Notes
    -----
    Valid for a nonzero liquid and mixture velocity and a no-slip holdup inside the flow-regime
    map; the correlation was fitted to air-water flow in 1 to 1.5 in. pipes at inclinations
    of -90 to +90 degrees and is used beyond that range. Reference: Beggs and Brill (1973), A
    Study of Two-Phase Flow in Inclined Pipes, J. Pet. Technol. 25(5), 607-617, with the
    regime map revised by Brill and Beggs; the formulation follows Shoham, Mechanistic
    Modeling of Gas-Liquid Two-Phase Flow in Pipes (2006), p. 59, as the original GEMINI
    implementation does. The flow regime and holdup use the
    correlation's US basis (ft/s, lbm/ft3, dyne/cm, ft). The SI friction and gravity terms
    then use the inputs converted back from that basis, not the inputs themselves: the
    m→ft→m, kg/m3→lbm/ft3→kg/m3 and Pa·s→cP→Pa·s round trips change the last bits, and the
    goldens were captured with them.
    """
    gas_velocity, liquid_velocity = units.m_to_ft(us_g), units.m_to_ft(us_l)
    diameter_ft = units.m_to_ft(diameter)
    us_g, us_l = units.ft_to_m(gas_velocity), units.ft_to_m(liquid_velocity)
    ops.check(
        ops.logical_and(liquid_velocity != 0, liquid_velocity + gas_velocity != 0),
        PhysicsError,
        "beggs_brill_dp: us_l = {us_l} m/s, us_g = {us_g} m/s; expected a nonzero liquid and "
        "mixture velocity (use darcy_weisbach_dp for single-phase flow)",
        us_l=us_l,
        us_g=us_g,
    )
    holdup, friction_multiplier = _holdup_and_friction_multiplier(
        gas_velocity,
        liquid_velocity,
        units.kgm3_to_lbmft3(rho_l),
        sigma / units.MILLI,
        diameter_ft,
        inclination,
    )
    rho_g, rho_l = (units.lbmft3_to_kgm3(units.kgm3_to_lbmft3(rho)) for rho in (rho_g, rho_l))
    mu_g, mu_l = (units.cp_to_pas(units.pas_to_cp(mu)) for mu in (mu_g, mu_l))
    diameter = units.ft_to_m(diameter_ft)
    roughness, length = (units.ft_to_m(units.m_to_ft(value)) for value in (roughness, length))

    friction = _no_slip_friction((us_g, us_l), (rho_g, rho_l), (mu_g, mu_l), diameter, roughness)
    friction = friction * friction_multiplier * length / diameter
    slip_density = (holdup * rho_l) + (1 - holdup) * rho_g
    gravity = hydrostatic_dp(slip_density, length, ops.sin(inclination))
    return friction, gravity


def _no_slip_friction(velocities, densities, viscosities, diameter, roughness):
    """Return ``0.5 rho_m u_m |u_m| f_n`` [Pa/-] of the no-slip mixture.

    ``velocities``, ``densities`` and ``viscosities`` are gas and liquid pairs. The caller
    multiplies by the two-phase multiplier and ``L / D`` in the published order.
    """
    us_g, us_l = velocities
    rho_g, rho_l = densities
    mu_g, mu_l = viscosities
    mixture_velocity = us_g + us_l
    no_slip_holdup = us_l / mixture_velocity
    density = (no_slip_holdup * rho_l) + (1 - no_slip_holdup) * rho_g
    viscosity = (no_slip_holdup * mu_l) + (1 - no_slip_holdup) * mu_g
    reynolds = reynolds_number(mixture_velocity, density, diameter, viscosity)
    friction_factor = (
        -0.8685
        * ops.log((1.964 * ops.log(reynolds) - 3.8215) / reynolds + roughness / (diameter * 3.71))
    ) ** -2
    return (0.5 * density * mixture_velocity * ops.abs(mixture_velocity)) * friction_factor


def _holdup_and_friction_multiplier(
    gas_velocity, liquid_velocity, liquid_density, surface_tension, diameter, inclination
):
    """Return the Beggs–Brill liquid holdup [-] and two-phase friction multiplier [-].

    Inputs are on the US basis: velocities [ft/s], liquid density [lbm/ft3], surface tension
    [dyne/cm] and diameter [ft], with a nonzero liquid and mixture velocity. The holdup is
    clamped to [0, 1]; a holdup clamped to zero, which a steep downhill inclination factor can
    produce, has no friction multiplier.
    """
    mixture_velocity = liquid_velocity + gas_velocity
    liquid_velocity_number = 1.938 * liquid_velocity * (liquid_density / surface_tension) ** 0.25
    no_slip_holdup = liquid_velocity / mixture_velocity
    froude = mixture_velocity**2 / (G_FT * diameter)
    holdup = _liquid_holdup(no_slip_holdup, liquid_velocity_number, froude, inclination)
    holdup = ops.minimum(holdup, 1)
    holdup = ops.maximum(holdup, 0)
    ops.check(
        holdup != 0,
        PhysicsError,
        "beggs_brill_dp: liquid holdup = 0 at inclination = {inclination} rad; expected a "
        "positive holdup (the downhill inclination factor removed all liquid)",
        holdup=holdup,
        inclination=inclination,
    )
    return holdup, _friction_multiplier(no_slip_holdup, holdup)


def _flow_regime(no_slip_holdup, froude):
    """Return the Beggs–Brill flow regime code and its L2 and L3 transition boundaries.

    The regime map follows Beggs and Brill (1973) as revised by Brill and Beggs: segregated
    for lambda < 0.01 and Fr < L1 or lambda >= 0.01 and Fr < L2; transition for
    lambda >= 0.01 and L2 <= Fr <= L3; intermittent for 0.01 <= lambda < 0.4 and
    L3 < Fr <= L1 or lambda >= 0.4 and L3 < Fr <= L4; distributed for lambda < 0.4 and
    Fr >= L1 or lambda >= 0.4 and Fr > L4. A no-slip holdup of exactly 0.4 therefore takes
    the upper range; it formerly matched no regime and divided by zero.

    The regime is one of ``_SEGREGATED``, ``_TRANSITION``, ``_INTERMITTENT`` and
    ``_DISTRIBUTED``, chosen by nested ``where`` in the order of the map; a pair outside the
    map raises.
    """
    l1 = 316 * no_slip_holdup**0.302
    l2 = 0.0009252 * no_slip_holdup**-2.4684
    l3 = 0.10 * no_slip_holdup**-1.4516
    l4 = 0.5 * no_slip_holdup**-6.738
    low, high = no_slip_holdup < 0.01, no_slip_holdup >= 0.01
    below, above = no_slip_holdup < 0.4, no_slip_holdup >= 0.4
    segregated = ops.logical_or(
        ops.logical_and(low, froude < l1), ops.logical_and(high, froude < l2)
    )
    transition = ops.logical_and(high, ops.logical_and(l2 <= froude, froude <= l3))
    intermittent = ops.logical_or(
        ops.logical_and(ops.logical_and(high, below), ops.logical_and(l3 <= froude, froude <= l1)),
        ops.logical_and(above, ops.logical_and(l3 <= froude, froude <= l4)),
    )
    distributed = ops.logical_or(
        ops.logical_and(below, froude >= l1), ops.logical_and(above, froude >= l4)
    )
    regime = ops.where(
        segregated,
        _SEGREGATED,
        ops.where(
            transition,
            _TRANSITION,
            ops.where(
                intermittent,
                _INTERMITTENT,
                ops.where(distributed, _DISTRIBUTED, _OUTSIDE_MAP),
            ),
        ),
    )
    ops.check(
        regime != _OUTSIDE_MAP,
        PhysicsError,
        "beggs_brill_dp: no-slip holdup = {no_slip_holdup}, Froude number = {froude}; "
        "expected finite values inside the flow-regime map",
        no_slip_holdup=no_slip_holdup,
        froude=froude,
    )
    return regime, l2, l3


def _liquid_holdup(no_slip_holdup, liquid_velocity_number, froude, inclination):
    """Return the inclined liquid holdup before clamping.

    Transition flow blends the segregated and intermittent holdups with the weight
    A = (L3 - Fr) / (L3 - L2). Every regime's holdup and inclination factors are evaluated and
    ``where`` selects the regime's, so the expressions equal the former per-regime branches.
    """
    regime, l2, l3 = _flow_regime(no_slip_holdup, froude)
    numbers = (no_slip_holdup, liquid_velocity_number, froude, inclination)
    segregated_holdup = _horizontal_holdup("segregated", no_slip_holdup, froude)
    intermittent_holdup = _horizontal_holdup("intermittent", no_slip_holdup, froude)
    distributed_holdup = _horizontal_holdup("distributed", no_slip_holdup, froude)
    downhill = _inclination_factor(_DOWNHILL, *numbers)
    segregated_uphill = _inclination_factor(_SEGREGATED_UPHILL, *numbers)
    intermittent_uphill = _inclination_factor(_INTERMITTENT_UPHILL, *numbers)
    is_downhill = inclination < 0

    horizontal = ops.where(
        regime == _SEGREGATED,
        segregated_holdup,
        ops.where(regime == _INTERMITTENT, intermittent_holdup, distributed_holdup),
    )
    factor = _regime_factor(
        regime, is_downhill, inclination >= 0, downhill, segregated_uphill, intermittent_uphill
    )
    weight = (l3 - froude) / (l3 - l2)
    segregated = segregated_holdup * ops.where(is_downhill, downhill, segregated_uphill)
    intermittent = intermittent_holdup * ops.where(is_downhill, downhill, intermittent_uphill)
    blended = weight * segregated + (1 - weight) * intermittent
    return ops.where(regime == _TRANSITION, blended, horizontal * factor)


def _horizontal_holdup(regime, no_slip_holdup, froude):
    """Return the horizontal-pipe holdup of one flow regime."""
    a, b, c = _HORIZONTAL_HOLDUP[regime]
    return a * (no_slip_holdup**b) / (froude**c)


def _regime_factor(
    regime, downhill, uphill, downhill_factor, segregated_factor, intermittent_factor
):
    """Return the inclination factor psi of a segregated, intermittent or distributed regime.

    Downhill flow uses the downhill coefficients in every regime and uphill distributed flow
    has psi = 1. A NaN inclination is neither downhill nor uphill and keeps the original
    fallback to the intermittent coefficients, which gives a NaN factor.
    """
    return ops.where(
        downhill,
        downhill_factor,
        ops.where(
            ops.logical_and(uphill, regime == _DISTRIBUTED),
            1,
            ops.where(
                ops.logical_and(uphill, regime == _SEGREGATED),
                segregated_factor,
                intermittent_factor,
            ),
        ),
    )


def _inclination_factor(coefficients, no_slip_holdup, liquid_velocity_number, froude, inclination):
    """Return psi = 1 + C (sin 1.8θ - 0.333 sin³ 1.8θ) with C = (1-λ) ln(d λ^e Nlv^f Fr^g)."""
    d, e, f, h = coefficients
    correction = ops.maximum(
        0,
        (1 - no_slip_holdup)
        * ops.log(d * (no_slip_holdup**e) * (liquid_velocity_number**f) * (froude**h)),
    )
    return 1 + correction * (ops.sin(1.8 * inclination) - 0.333 * (ops.sin(1.8 * inclination)) ** 3)


def _friction_multiplier(no_slip_holdup, holdup):
    """Return the two-phase friction multiplier exp(s) with y = lambda / holdup²."""
    y = no_slip_holdup / holdup**2
    log_y = ops.log(y)
    s = ops.where(
        ops.logical_and(y > 1, y < 1.2),
        ops.log(2.2 * y - 1.2),
        log_y / (-0.0523 + 3.182 * log_y - 0.8725 * (log_y) ** 2 + 0.01853 * (log_y) ** 4),
    )
    return ops.exp(s)


@dataclass(frozen=True)
class PathResult:
    """Uncorrected path result: pressures [Pa], temperatures [K]."""

    p_out: float
    T_out: float
    friction_pressure_drop: float
    gravity_pressure_drop: float
    section_pressure: list[float]
    section_temperature: list[float]


@ops.physics
def quadratic_pressure_drop(reference_drop: float, flow: float, reference_flow: float) -> float:
    """Return the pressure drop [Pa] of a fixed resistance: ``dp_ref * (q / q_ref)^2``.

    Parameters
    ----------
    reference_drop : float
        Pressure drop [Pa] at the reference flow.
    flow, reference_flow : float
        Flow and its nonzero reference, both in one unit: mass [kg/s] or volume [m3/s].

    Returns
    -------
    float
        Pressure drop [Pa]; a reverse flow gives the same positive drop.

    Notes
    -----
    Valid for fully turbulent flow through a fixed geometry at constant density, where the loss
    coefficient does not depend on the Reynolds number. Reference: Idelchik, Handbook of Hydraulic
    Resistance, 4th ed. (2007), chapter 1: ``dp = zeta rho u^2 / 2`` with constant ``zeta``.
    """
    return reference_drop * (flow / reference_flow) ** 2


@ops.physics
def valve_pressure_drop(mass_flow: float, density: float, flow_coefficient: float) -> float:
    """Return the liquid pressure drop [Pa] of a valve: ``dp = (rho / rho_0) (q / Kv)^2``.

    Parameters
    ----------
    mass_flow, density : float
        Mass flow [kg/s] and liquid density [kg/m3]; ``q = m_dot / rho``.
    flow_coefficient : float
        Flow coefficient Kv [m3/s/Pa^0.5] at the opening, nonzero where the flow is nonzero.

    Returns
    -------
    float
        Pressure drop [Pa], zero at zero flow.

    Notes
    -----
    Non-choked turbulent liquid flow without a Reynolds or piping correction. Reference: IEC
    60534-2-1:2011, with ``rho_0`` = ``VALVE_REFERENCE_DENSITY``.
    """
    return ops.where(
        mass_flow == 0,
        0.0,
        quadratic_pressure_drop(
            density / VALVE_REFERENCE_DENSITY, mass_flow / density, flow_coefficient
        ),
    )


@ops.physics
def hydrostatic_dp(rho: float, height: float, inclination_sine: float = 1.0) -> float:
    """Return the hydrostatic pressure difference [Pa] of a fluid column, ``dp = rho g h s``.

    Parameters
    ----------
    rho, height : float
        Density [kg/m3] and signed length of the column [m].
    inclination_sine : float
        Sine of the column's angle from horizontal [-]; the default 1 is a vertical column
        and ``height`` is then the vertical height.

    Returns
    -------
    float
        Pressure difference [Pa], positive down the column.

    Notes
    -----
    Valid for a static or slow fluid of uniform density. Reference: the hydrostatic balance
    ``dp / dz = rho g`` (White, Fluid Mechanics, 8th ed., section 2.3) with GEMINI's
    ``G`` = 9.81 m/s2.
    """
    return rho * G * height * inclination_sine


@ops.physics
def pipe_path_profile(
    path: geometry.PipePath,
    stream: Stream,
    fluid: Fluid,
    direction: Literal["up", "down"],
    heat_transfer_coefficient: float,
    ambient_temperature: float,
    correlation: Literal["darcy_weisbach"] = "darcy_weisbach",
    correlation_2p: Literal["BeggsBrill"] = "BeggsBrill",
) -> PathResult:
    """March the pressure and temperature of a stream along a pipe path.

    Per section ``p_out = p -/+ (friction_pressure_drop + gravity_pressure_drop)`` and ``T_out = T
    -/+ dT``, with the drops of ``darcy_weisbach_dp`` (liquid only) or ``beggs_brill_dp`` (free
    gas) and the temperature change of ``heat_transfer.pipe_temperature_change``; the signs are
    those of the traversal direction.

    Parameters
    ----------
    path : PipePath
        Sections ordered from surface to bottom [m, rad].
    stream : Stream
        Inlet mass flow [kg/s], pressure [Pa] and temperature [K].
    fluid : Fluid
        Property model with properties(p, T).
    direction : str
        Traversal direction, 'up' or 'down' (case and surrounding spaces ignored); the flow
        sign is independent.
    heat_transfer_coefficient, ambient_temperature : float
        Heat transfer coefficient [W/m2/K] and ambient temperature [K].
    correlation, correlation_2p : str
        Single-phase and two-phase correlation names.

    Returns
    -------
    PathResult
        Uncorrected pressure [Pa], temperature [K], drops [Pa], and traversed profiles.

    Notes
    -----
    Valid where its section correlations are: steady single-phase or no-slip two-phase flow in
    circular pipes with the property snapshot of ``fluid``. Marched pressures never fall below
    ``MIN_PATH_PRESSURE`` (0.001 Pa), so a path whose drops exceed the inlet pressure keeps a
    positive absolute pressure, as in DPDT. Reference: the section equations (Swamee and Jain
    1976; Beggs and Brill 1973) marched as in GEMINI's DPDT; the loop over sections is
    configuration-sized and reads the plain path geometry.
    """
    direction, sections = _traversal(path, direction)
    if correlation != "darcy_weisbach" or correlation_2p != "BeggsBrill":
        raise ValidationError(
            f"pipe_path_profile: correlation = {correlation!r}, correlation_2p = "
            f"{correlation_2p!r}; expected 'darcy_weisbach' and 'BeggsBrill'",
            code="unknown_name",
        )
    p, T = stream.p, stream.T
    flow = fluid_physics.volume_flow(stream.m_dot, fluid.properties(p, T).density)
    pressures, temperatures = [], []
    friction_pressure_drop = gravity_pressure_drop = 0.0
    for section in sections:
        friction, gravity, delta_T = _section_drops(
            section, p, T, flow, fluid, heat_transfer_coefficient, ambient_temperature
        )
        if direction == "down":
            p, T = ops.maximum(MIN_PATH_PRESSURE, p + friction + gravity), T + delta_T
        else:
            p, T = ops.maximum(MIN_PATH_PRESSURE, p - friction - gravity), T - delta_T
        pressures.append(p)
        temperatures.append(T)
        friction_pressure_drop += friction
        gravity_pressure_drop += gravity
    return PathResult(p, T, friction_pressure_drop, gravity_pressure_drop, pressures, temperatures)


def _traversal(path, direction):
    """Return the normalised direction and the path sections in traversal order."""
    direction = direction.strip().lower()
    if direction not in {"up", "down"}:
        raise ValidationError(
            f"pipe path: direction = {direction!r}; expected 'up' or 'down'", code="unknown_name"
        )
    sections = path.sections if direction == "down" else list(reversed(path.sections))
    return direction, sections


def _section_drops(section, p, T, flow, fluid, heat_transfer_coefficient, ambient_temperature):
    """Return friction and gravity drops [Pa] and the temperature change [K] of one section.

    Two-phase reverse flow passes the velocity magnitudes to Beggs–Brill and reverses
    the friction sign, as Darcy–Weisbach does through ``abs(velocity) * velocity``.

    The two-phase model is chosen by ``fluid.gas_mass_fraction``, which is fixed in a trace: a
    liquid-only fluid never reaches Beggs–Brill. With free gas the gas mass flow is zero only
    at zero flow, which is the zero-flow case, so the structural test equals the former test of
    the gas mass flow. At zero flow every branch is still evaluated, Beggs–Brill's check on the
    liquid velocity fails there and ``where`` drops its error for the zero drops; the two drops
    are read by index because a failed result cannot be unpacked. The heat loss
    still receives a liquid flow of 1 kg/s at zero flow, because a direct call on arrays raises
    a failing check at once and this function is called that way.

    NOTE(refactor): DPDT's zero-flow branch suppresses gravity as well as friction.

    NOTE(refactor): the gas superficial velocity is ``m_g / rho_g / area``. The original
    ``gmf / rho_g / area`` left out the mass flow, so regime and holdup did not follow the flow;
    ``test_the_gas_superficial_velocity_is_the_gas_mass_flow_over_its_density_and_area`` holds a
    hand calculation. ``rho_g`` is the density of the free gas at this section's pressure and
    temperature, ideal-gas for a fluid with a ``gas_composition``.
    """
    stopped = flow == 0
    f = fluid.properties(p, T)
    mass = flow * f.density
    m_l, m_g = (1 - f.gmf) * mass, f.gmf * mass
    us_l = geometry.mean_velocity(m_l, f.rho_l, section.inner_diameter)
    rho_g = fluid.gas_density_at(p, T)
    us_g = geometry.mean_velocity(m_g, rho_g, section.inner_diameter)
    shape = (section.inner_diameter, section.roughness, section.length)
    if fluid.gas_mass_fraction == 0:
        friction, gravity = darcy_weisbach_dp(us_l, f.rho_l, section.inclination, f.mu_l, *shape)
    else:
        drops = beggs_brill_dp(
            ops.abs(us_g),
            ops.abs(us_l),
            rho_g,
            f.rho_l,
            section.inclination,
            f.mu_g,
            f.mu_l,
            f.sigma,
            *shape,
        )
        friction, gravity = drops[0], drops[1]
        friction = ops.where(us_l < 0, -friction, friction)
    delta_T = heat_transfer.pipe_temperature_change(
        T,
        heat_transfer_coefficient,
        geometry.lateral_area(section.inner_diameter, section.length),
        ops.where(stopped, 1.0, m_l),
        m_g,
        f.cp_l,
        f.cp_g,
        ambient_temperature,
    )
    return (
        ops.where(stopped, 0.0, friction),
        ops.where(stopped, 0.0, gravity),
        ops.where(stopped, 0.0, delta_T),
    )


@ops.physics
def radial_pressure_drops(
    volume_flow: float,
    viscosity: float,
    permeability: float,
    thickness: float,
    drainage_radius: float,
    wellbore_radius: float,
    skin: float,
) -> tuple[float, float]:
    """Return the radial Darcy and skin pressure drops [Pa] of an inflow to a well (Akin 2019).

    ``dp_flow = q mu ln(r_e / r_w) / (2 pi k h)`` and ``dp_skin = q mu s / (2 pi k h)``.

    Parameters
    ----------
    volume_flow, viscosity : float
        Liquid volume flow [m3/s] and dynamic viscosity [Pa s].
    permeability, thickness, drainage_radius, wellbore_radius : float
        Permeability [m2], reservoir thickness and radii [m].
    skin : float
        Skin factor [-].

    Returns
    -------
    tuple of float
        Flow and skin pressure drops [Pa].

    Notes
    -----
    Valid for steady-state single-phase radial Darcy flow of an incompressible liquid in a
    homogeneous reservoir of constant thickness, ``r_e > r_w``; positive permeability,
    thickness and radii are required. Reference: Darcy (1856) in radial form, with the skin
    factor of van Everdingen (1953), The Skin Effect and Its Influence on the Productive
    Capacity of a Well, Trans. AIME 198, 171-176.
    """
    smallest = ops.minimum(
        ops.minimum(ops.minimum(permeability, thickness), drainage_radius), wellbore_radius
    )
    ops.check(
        ops.logical_not(smallest <= 0),
        PhysicsError,
        "radial_pressure_drops: permeability = {permeability} m2, thickness = {thickness} m, "
        "drainage_radius = {drainage_radius} m, wellbore_radius = {wellbore_radius} m; "
        "expected positive values",
        permeability=permeability,
        thickness=thickness,
        drainage_radius=drainage_radius,
        wellbore_radius=wellbore_radius,
    )
    denominator = 2 * math.pi * permeability * thickness
    return (
        volume_flow * viscosity * ops.log(drainage_radius / wellbore_radius) / denominator,
        volume_flow * viscosity * skin / denominator,
    )


def radial_index(
    viscosity: float,
    permeability: float,
    thickness: float,
    drainage_radius: float,
    wellbore_radius: float,
    skin: float,
) -> float:
    """Return the productivity or injectivity index [m3/s/Pa] of a well in a radial reservoir.

    Parameters
    ----------
    viscosity : float
        Liquid dynamic viscosity [Pa s].
    permeability, thickness, drainage_radius, wellbore_radius : float
        Permeability [m2], reservoir thickness and radii [m].
    skin : float
        Skin factor [-].

    Returns
    -------
    float
        ``J = 2 pi k h / (mu (ln(r_e / r_w) + s))``: flow per pressure difference.

    Notes
    -----
    The inverse of ``radial_pressure_drops`` at a unit flow, valid as that function is.
    Source: Darcy (1856) in radial form with the skin of van Everdingen (1953), as cited there.
    """
    flow_drop, skin_drop = radial_pressure_drops(
        1.0, viscosity, permeability, thickness, drainage_radius, wellbore_radius, skin
    )
    return 1 / (flow_drop + skin_drop)


def hydrostatic_pressure(rho: float, depth: float) -> float:
    """Return the absolute pressure [Pa] of a liquid column open to the atmosphere at ``depth``.

    Parameters
    ----------
    rho : float
        Liquid density [kg/m3].
    depth : float
        True vertical depth [m].

    Returns
    -------
    float
        ``p = p_atm + rho g z`` with the atmosphere of a normal cubic metre.

    Notes
    -----
    The pressure of a reservoir in hydrostatic equilibrium with the surface, the usual first
    estimate of an aquifer pressure.
    Validity: A static column of uniform density.
    Source: The hydrostatic balance, as in ``hydrostatic_dp`` (White, Fluid Mechanics, 8th ed.,
    section 2.3).
    """
    return gas.NORMAL_PRESSURE + hydrostatic_dp(rho, depth)


def pump_setting_depth(
    depth: float, reservoir_pressure: float, drawdown: float, intake_pressure: float, rho: float
) -> float:
    """Return the shallowest pump depth [m] that keeps ``intake_pressure`` at the intake.

    Parameters
    ----------
    depth : float
        True vertical depth of the reservoir [m].
    reservoir_pressure, drawdown, intake_pressure : float
        Reservoir pressure, drawdown at the design flow and pressure wanted at the intake [Pa].
    rho : float
        Liquid density [kg/m3].

    Returns
    -------
    float
        ``z = D - (p_r - dp - p_i) / (rho g)``, at least zero.

    Notes
    -----
    The flowing bottomhole pressure carries the liquid column up to the depth where it falls to the
    intake pressure; friction below the pump is neglected against that pressure.
    Validity: A vertical well and uniform density.
    Source: The hydrostatic balance, as in ``hydrostatic_dp``; a sizing rule, no published source.
    """
    column = (reservoir_pressure - drawdown - intake_pressure) / hydrostatic_dp(rho, 1.0)
    return max(0.0, depth - column)


def design_pump_head(
    wellhead_pressure: float,
    reservoir_pressure: float,
    drawdown: float,
    rho: float,
    mu: float,
    depth: float,
    diameter: float,
    roughness: float,
    flow: float,
) -> float:
    """Return the head [Pa] a production pump adds to reach a wellhead pressure at a design flow.

    Parameters
    ----------
    wellhead_pressure, reservoir_pressure, drawdown : float
        Wanted wellhead pressure, reservoir pressure and drawdown at the design flow [Pa].
    rho, mu : float
        Liquid density [kg/m3] and viscosity [Pa s].
    depth, diameter, roughness : float
        Vertical well depth, internal diameter and roughness [m].
    flow : float
        Design volume flow [m3/s].

    Returns
    -------
    float
        ``H = p_wh + rho g D + dp_f - (p_r - dp)``, at least zero.

    Notes
    -----
    A pressure balance over the well, with the friction of ``darcy_weisbach_dp``.
    Validity: The range of ``darcy_weisbach_dp``.
    Source: A plain pressure balance; no published source is needed.
    """
    velocity = geometry.mean_velocity(flow * rho, rho, diameter)
    friction, gravity = darcy_weisbach_dp(
        velocity, rho, math.pi / 2, mu, diameter, roughness, depth
    )
    return max(0.0, wellhead_pressure + gravity + friction - reservoir_pressure + drawdown)


@ops.physics
def corrosion_profile(
    path: geometry.PipePath,
    stream: Stream,
    fluid: Fluid,
    direction: Literal["up", "down"],
    heat_transfer_coefficient: float,
    ambient_temperature: float,
    chemistry: dict,
    model: Literal["NORSOK", "DLM", "DLD"] = "NORSOK",
) -> list[float]:
    """Return the CO2 corrosion rate [mm/year] of each section along the hydraulic profile.

    Each section takes the marched pressure and temperature of ``pipe_path_profile`` and the
    liquid flow ``q = |m| / rho`` at them, then the rate of ``corrosion.co2_corrosion_rate``.

    Parameters
    ----------
    path : PipePath
        Surface-to-bottom intervals [m, rad].
    stream : Stream
        Signed mass flow [kg/s], inlet pressure [Pa] and temperature [K].
    fluid : Fluid
        SI property model.
    direction : str
        Traversal direction, up or down [-].
    heat_transfer_coefficient, ambient_temperature : float
        Heat transfer coefficient [W/m2/K] and ambient temperature [K].
    chemistry : dict
        Keyword arguments for co2_corrosion_rate in its documented SI units.
    model : str
        NORSOK, DLM or DLD correlation [-].

    Returns
    -------
    list of float
        Wall penetration rates [mm/year] in traversal order.

    Notes
    -----
    Valid where ``co2_corrosion_rate`` is (NORSOK M-506: 5 to 150 degC, pH 3.5 to 6.5) and a
    nonzero flow. Reference: GEMINI WIMS composition of DPDT and the CO2 correlations (NORSOK
    M-506; de Waard and Lotz); see pipe_path_profile and corrosion.co2_corrosion_rate. The
    loop over sections reads the plain path geometry.
    """
    result = pipe_path_profile(
        path, stream, fluid, direction, heat_transfer_coefficient, ambient_temperature
    )
    _, sections = _traversal(path, direction)
    rates = []
    for section, p, T in zip(sections, result.section_pressure, result.section_temperature):
        f = fluid.properties(p, T)
        rates.append(
            corrosion.co2_corrosion_rate(
                model,
                temperature=T,
                pressure=p,
                water_flow_rate=fluid_physics.volume_flow(ops.abs(stream.m_dot), f.density),
                water_density=f.rho_l,
                water_viscosity=f.mu_l,
                diameter=section.inner_diameter,
                roughness=section.roughness,
                **chemistry,
            )
        )
    return rates


@ops.physics
def erosion_check(path: geometry.PipePath, stream: Stream, fluid: Fluid) -> dict:
    """Compare section velocities with the API erosional velocity limit.

    Per section ``u = |m| / (rho A)`` and the limit ``u_e = C / sqrt(rho)`` of
    ``erosion.api_erosional_velocity`` at the inlet mixture density.

    Parameters
    ----------
    path : PipePath
        Surface-to-bottom pipe intervals [m, rad].
    stream : Stream
        Mass flow [kg/s], pressure [Pa] and temperature [K].
    fluid : Fluid
        SI property model.

    Returns
    -------
    dict
        Section velocities and limit [m/s], dimensionless ratios and alarm flags.

    Notes
    -----
    Valid for clean, solids-free service; the limit uses the density at the inlet conditions
    for every section. Reference: API RP 14E (Recommended Practice for Design and Installation
    of Offshore Production Platform Piping Systems), as implemented in GEMINI WIMS.
    """
    density = fluid.properties(stream.p, stream.T).density
    limit = erosion.api_erosional_velocity(density)
    velocity = [
        geometry.mean_velocity(ops.abs(stream.m_dot), density, s.inner_diameter)
        for s in path.sections
    ]
    sections = [erosion.api_velocity_comparison(v, limit) for v in velocity]
    return {
        "velocity": velocity,
        "limit": limit,
        "sections": sections,
        "alarm": reduce(ops.logical_or, (s["exceeds_api_limit"] for s in sections), False),
    }
