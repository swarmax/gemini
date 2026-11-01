"""Ground and aquifer heat transport: doublet breakthrough, conduction shapes, Ramey profiles.

The functions are plain SI relations used by the subsurface equipment: the thermal
breakthrough of a geothermal doublet (Gringarten and Sauty 1975), the conduction conductance
of buried storage volumes (Incropera et al.; Carslaw and Jaeger 1959), the steady-flux
borehole cell resistance (Hellstrom 1991) and the transient rock resistance and fluid
temperature profile of a well in a linear geothermal gradient (Ramey 1962).
"""

import math

from gemini import ops, units
from gemini.errors import PhysicsError
from gemini.ops import Constant
from gemini.physics import constants, heat_transfer

EULER_GAMMA = 0.5772156649015329
"""Euler-Mascheroni constant [-] of the line-source long-time asymptote."""

MIN_RAMEY_FOURIER = Constant(
    "MIN_RAMEY_FOURIER",
    25.0,
    "-",
    "smallest dimensionless time alpha*t/r**2 for which the Ramey asymptote is within 1 %",
)

HALF_YEAR = 182.625 * units.SECONDS_PER_DAY
"""Default storage period [s] of an aquifer store: one charge or discharge season."""

_SMALL_ANGLE = 0.1
"""Streamline angle [rad] below which ``sin - theta*cos`` uses its Taylor series."""

_ANGLE_MARGIN = 1e-12
"""Relative distance [-] from 0 and pi of the streamline-angle root bracket."""


@ops.physics
@ops.physics
def reservoir_temperature(
    surface_temperature: float,
    gradient: float,
    depth: float,
    reference_depth: float,
    reference_temperature: float | None = None,
) -> float:
    """Return the reservoir temperature [K] at a depth, from a reference point or the surface.

    Parameters
    ----------
    surface_temperature : float
        Mean temperature at the surface [K].
    gradient : float
        Geothermal gradient [K/m].
    depth : float
        True vertical depth [m] where the temperature is wanted.
    reference_depth : float
        Depth [m] of the reference temperature.
    reference_temperature : float, optional
        Measured temperature [K] at ``reference_depth``; without it the temperature is the
        geotherm from the surface.

    Returns
    -------
    float
        ``T = T_ref + g (z - z_ref)`` with the reference temperature given, else
        ``T = T_s + g z``.

    Notes
    -----
    Linear conductive geotherm (see ``geotherm_temperature``): a measured temperature anchors the
    line at its depth and the gradient carries it to another depth, so the given value is never
    overridden by the surface value.
    Reference: Turcotte and Schubert, Geodynamics, chapter 4.
    """
    if reference_temperature is None:
        return geotherm_temperature(surface_temperature, gradient, depth)
    return reference_temperature + gradient * (depth - reference_depth)


@ops.physics
def reservoir_pressure(
    reference_pressure: float, density: float, depth: float, reference_depth: float
) -> float:
    """Return the reservoir pressure [Pa] at a depth, from the pressure at a reference depth.

    Parameters
    ----------
    reference_pressure : float
        Absolute pressure [Pa] at ``reference_depth``.
    density : float
        Density [kg/m3] of the brine in the column between the two depths, taken as constant.
    depth : float
        True vertical depth [m] where the pressure is wanted.
    reference_depth : float
        Depth [m] of the reference pressure.

    Returns
    -------
    float
        ``p = p_ref + rho g (z - z_ref)`` with ``g`` the standard gravity of
        ``gemini.physics.constants.G``.

    Notes
    -----
    The hydrostatic balance of a static column of uniform density (White, Fluid Mechanics, 8th
    ed., section 2.3); the pressure at the reference depth is the measured anchor.
    """
    return reference_pressure + density * constants.G * (depth - reference_depth)


@ops.physics
def aquifer_volumetric_heat_capacity(
    porosity: float, fluid_heat_capacity: float, rock_heat_capacity: float
) -> float:
    """Return the bulk volumetric heat capacity [J/m3/K] of a saturated aquifer.

    Parameters
    ----------
    porosity : float
        Connected porosity [-] in [0, 1].
    fluid_heat_capacity, rock_heat_capacity : float
        Positive volumetric heat capacities of the pore fluid and of the rock grains [J/m3/K].

    Notes
    -----
    Volume-weighted mixing rule (rho c)_a = phi (rho c)_w + (1 - phi) (rho c)_r, which assumes
    local thermal equilibrium between fluid and grains (Bear 1972, Dynamics of Fluids in
    Porous Media).
    """
    _require_positive("aquifer_volumetric_heat_capacity", fluid=fluid_heat_capacity)
    _require_positive("aquifer_volumetric_heat_capacity", rock=rock_heat_capacity)
    ops.check(
        ops.logical_and(porosity >= 0, porosity <= 1),
        PhysicsError,
        "aquifer_volumetric_heat_capacity: porosity = {porosity}; expected a value in [0, 1]",
        porosity=porosity,
    )
    return porosity * fluid_heat_capacity + (1 - porosity) * rock_heat_capacity


DOUBLET_WELL_SPACING = 1000.0
"""Distance [m] between the wells of a doublet at reservoir level, as its drainage radius.

The base case of Willems (2016) for the West Netherlands Basin, the lower end of the 1 to 2 km of
Dutch doublets; the well distance is the length in the radial inflow of DoubletCalc (Mijnlieff et
al. 2013, EGC, "Geothermal energy and support schemes in the Netherlands", slide 14).
"""


@ops.physics
def geotherm_temperature(surface_temperature: float, gradient: float, depth: float) -> float:
    """Return the undisturbed ground temperature [K] at a depth, ``T = T_s + g z``.

    Parameters
    ----------
    surface_temperature : float
        Mean temperature at the surface [K], positive.
    gradient : float
        Geothermal gradient [K/m].
    depth : float
        True vertical depth [m], nonnegative.

    Returns
    -------
    float
        Temperature [K].

    Notes
    -----
    Linear conductive geotherm, the steady conduction profile of a layer of uniform conductivity
    without heat production. Valid where conduction dominates and the gradient is constant with
    depth.
    Reference: Turcotte and Schubert, Geodynamics, chapter 4.
    """
    return surface_temperature + gradient * depth


@ops.physics
def doublet_breakthrough_volume(
    well_spacing: float,
    thickness: float,
    aquifer_heat_capacity: float,
    fluid_heat_capacity: float,
) -> float:
    """Return the injected volume [m3] at which the cold front reaches the producer.

    Parameters
    ----------
    well_spacing, thickness : float
        Positive distance between the injector and producer and aquifer thickness [m].
    aquifer_heat_capacity, fluid_heat_capacity : float
        Positive volumetric heat capacities of the saturated aquifer and the fluid [J/m3/K].

    Returns
    -------
    float
        V_B = pi L**2 H (rho c)_a / (3 (rho c)_w) [m3]; at a constant rate Q the breakthrough
        time is V_B / Q.

    Notes
    -----
    Reference: Gringarten and Sauty (1975), A theoretical study of heat extraction from
    aquifers with uniform regional flow, J. Geophys. Res. 80(35), 4956-4962, breakthrough time
    without heat exchange with the confining beds, t_B = pi L**2 H (rho c)_a / (3 Q (rho c)_w).
    Valid for a balanced doublet of fully penetrating wells in a homogeneous, isotropic,
    confined aquifer of constant thickness without regional flow.
    """
    _require_positive("doublet_breakthrough_volume", well_spacing=well_spacing)
    _require_positive("doublet_breakthrough_volume", thickness=thickness)
    _require_positive("doublet_breakthrough_volume", aquifer=aquifer_heat_capacity)
    _require_positive("doublet_breakthrough_volume", fluid=fluid_heat_capacity)
    return math.pi * well_spacing**2 * thickness * aquifer_heat_capacity / (3 * fluid_heat_capacity)


@ops.physics
def doublet_cold_fraction(volume_ratio: float) -> float:
    """Return the share [-] of the produced flow that arrives at the injection temperature.

    Parameters
    ----------
    volume_ratio : float
        Nonnegative injected volume divided by the breakthrough volume V / V_B [-].

    Returns
    -------
    float
        Zero up to breakthrough, then theta / pi, where the streamline leaving the injector at
        angle theta to the well axis has the thermal travel time t / t_B = V / V_B.

    Notes
    -----
    The streamlines of a doublet (dipole) are circles through both wells. The streamline that
    leaves the injector at angle theta carries the travel time
    t(theta) / t_B = 3 (sin theta - theta cos theta) / sin(theta)**3 and bounds the share
    theta / pi of the flow (Gringarten and Sauty 1975). With piston
    displacement and no heat exchange with the confining beds, every streamline whose travel
    time has passed delivers water at the injection temperature, so the producer temperature
    is T_res - (theta / pi) (T_res - T_inj). The decline starts with a square-root shape,
    theta ~ sqrt(5 (V / V_B - 1) / 2), and tends to one as V / V_B grows without bound.
    """
    ops.check(
        volume_ratio >= 0,
        PhysicsError,
        "doublet_cold_fraction: volume_ratio = {volume_ratio}; expected a value >= 0",
        volume_ratio=volume_ratio,
    )
    upper = math.pi * (1 - _ANGLE_MARGIN)
    angle = ops.brentq(
        _travel_time_residual, _ANGLE_MARGIN, upper, args=(volume_ratio,), xtol=1e-14
    )
    return ops.where(
        volume_ratio <= 1,
        0.0,
        ops.where(_dipole_travel_time(upper) <= volume_ratio, 1.0, angle / math.pi),
    )


@ops.physics
def cylinder_store_conductance(
    conductivity: float, diffusivity: float, volume: float, height: float, period: float
) -> float:
    """Return the period-mean conduction conductance [W/K] of a cylindrical heat store.

    Parameters
    ----------
    conductivity, diffusivity : float
        Positive thermal conductivity [W/m/K] and diffusivity [m2/s] of the surroundings.
    volume : float
        Nonnegative thermal volume of the store [m3].
    height : float
        Positive height of the store, the aquifer or well-screen thickness [m].
    period : float
        Positive storage period over which the conduction boundary layer grows [s].

    Returns
    -------
    float
        UA = 2 k A / sqrt(pi alpha t_p) with A = 2 pi R**2 + 2 pi R H and
        R = sqrt(V / (pi H)) [W/K]; zero for zero volume.

    Notes
    -----
    A step of the store temperature drives the flux k dT / sqrt(pi alpha t) into a
    semi-infinite medium (Carslaw and Jaeger 1959, Conduction of Heat in Solids);
    its mean over the period t_p is 2 k dT / sqrt(pi alpha t_p). Applied to the whole
    envelope (top, bottom and side) of the cylinder of the store's thermal radius, it makes
    the losses scale with the area-to-volume ratio, the governing quantity of ATES thermal
    recovery (Bloemendal and Hartog 2018, Geothermics 71, 306-319). Valid while the
    penetration depth sqrt(alpha t_p) is small against R and H.
    """
    _require_positive("cylinder_store_conductance", conductivity=conductivity)
    _require_positive("cylinder_store_conductance", diffusivity=diffusivity)
    _require_positive("cylinder_store_conductance", height=height)
    _require_positive("cylinder_store_conductance", period=period)
    ops.check(
        ops.logical_not(ops.logical_or(ops.isnan(volume), volume < 0)),
        PhysicsError,
        "cylinder_store_conductance: volume = {volume} m3; expected >= 0",
        volume=volume,
    )
    radius = ops.sqrt(volume / (math.pi * height))
    area = 2 * math.pi * radius * (radius + height)
    return 2 * conductivity * area / ops.sqrt(math.pi * diffusivity * period)


@ops.physics
def vertical_cylinder_conductance(
    conductivity: float,
    length: float,
    diameter: float,
    *,
    error: type[Exception] = PhysicsError,
    code: str | None = None,
    context: str = "",
) -> float:
    """Return the steady conductance [W/K] of a vertical cylinder below an isothermal surface.

    Parameters
    ----------
    conductivity : float
        Positive thermal conductivity of the ground [W/m/K].
    length, diameter : float
        Positive depth and diameter of the cylinder whose top is at the surface [m].
    error : type of Exception, optional
        Class raised for an invalid input; a caller that reports the failure as its own
        configuration error passes it with a ``context`` prefix for the message.
    code : str, optional
        The ``gm.errors.CODES`` entry of that error, the default of its class when ``None``.
    context : str, optional
        Text placed before the function name in the message of an error.

    Returns
    -------
    float
        UA = k S with S = 2 pi L / ln(4 L / D) [W/K].

    Notes
    -----
    Reference: Incropera et al., Fundamentals of Heat and Mass Transfer, table 4.1, vertical
    cylinder in a semi-infinite medium, derived for L >> D. Raises ``PhysicsError`` for
    ln(4 L / D) < 1 (L < 0.68 D), where the shape factor no longer applies.
    """
    function = f"{context}vertical_cylinder_conductance"
    _require_positive(function, error, code, conductivity=conductivity)
    _require_positive(function, error, code, length=length)
    _require_positive(function, error, code, diameter=diameter)
    logarithm = ops.log(4 * length / diameter)
    ops.check(
        ops.logical_not(logarithm < 1),
        error,
        "{function}: length = {length} m, diameter = {diameter} m; "
        "expected ln(4 length / diameter) >= 1",
        code=code,
        function=function,
        length=length,
        diameter=diameter,
        logarithm=logarithm,
    )
    return conductivity * 2 * math.pi * length / logarithm


@ops.physics
def steady_flux_resistance(
    conductivity: float,
    borehole_radius: float,
    cell_radius: float,
    *,
    error: type[Exception] = PhysicsError,
    code: str | None = None,
    context: str = "",
) -> float:
    """Return the ground resistance [m K/W] between a borehole wall and its cell's mean.

    Parameters
    ----------
    conductivity : float
        Positive ground thermal conductivity [W/m/K].
    borehole_radius, cell_radius : float
        Borehole radius and the larger equivalent radius of its ground cell [m].
    error : type of Exception, optional
        Class raised for an invalid input; a caller that reports the failure as its own
        configuration error passes it with a ``context`` prefix for the message.
    code : str, optional
        The ``gm.errors.CODES`` entry of that error, the default of its class when ``None``.
    context : str, optional
        Text placed before the function name in the message of an error.

    Returns
    -------
    float
        R_sf = (ln(r_e / r_b) / (1 - x)**2 - 1 / (2 (1 - x)) - 1 / 4) / (2 pi k) with
        x = (r_b / r_e)**2 [m K/W].

    Notes
    -----
    Steady-flux regime of a borehole in a cylindrical cell with an adiabatic outer radius
    r_e, where the whole cell warms or cools at the same rate (Hellstrom 1991, Ground Heat
    Storage, Lund University). The expression is the exact annulus solution with
    a uniform heat sink; for r_b << r_e it reduces to Hellstrom's (ln(r_e / r_b) - 3/4) /
    (2 pi k). The regime is reached after about r_e**2 / (4 alpha).
    """
    function = f"{context}steady_flux_resistance"
    _require_positive(function, error, code, conductivity=conductivity)
    _require_positive(function, error, code, borehole_radius=borehole_radius)
    ops.check(
        ops.logical_not(cell_radius <= borehole_radius),
        error,
        "{function}: cell_radius = {cell_radius} m; expected more than "
        "borehole_radius = {borehole_radius} m",
        code=code,
        function=function,
        cell_radius=cell_radius,
        borehole_radius=borehole_radius,
    )
    x = (borehole_radius / cell_radius) ** 2
    shape = ops.log(cell_radius / borehole_radius) / (1 - x) ** 2 - 1 / (2 * (1 - x)) - 0.25
    return shape / (2 * math.pi * conductivity)


@ops.physics
def ramey_time_function(
    time: float,
    diffusivity: float,
    radius: float,
    *,
    error: type[Exception] = PhysicsError,
    code: str | None = None,
    context: str = "",
) -> float:
    """Return Ramey's dimensionless transient conduction function f(t) [-].

    Parameters
    ----------
    time : float
        Positive time since the well started to exchange heat [s].
    diffusivity : float
        Positive rock thermal diffusivity [m2/s].
    radius : float
        Positive borehole (outer heat-exchange) radius [m].
    error : type of Exception, optional
        Class raised for an invalid input; a caller that reports the failure as its own
        configuration error passes it with a ``context`` prefix for the message.
    code : str, optional
        The ``gm.errors.CODES`` entry of that error, the default of its class when ``None``.
    context : str, optional
        Text placed before the function name in the message of an error.

    Returns
    -------
    float
        f(t) = ln(2 sqrt(alpha t) / r) - gamma / 2 [-]; the rock adds the resistance
        f(t) / (2 pi k) per unit length.

    Notes
    -----
    Reference: Ramey (1962), Wellbore heat transmission, J. Petroleum Technology 14(4),
    427-435, long-time line-source approximation f(t) = -ln(r / (2 sqrt(alpha t))) - 0.290;
    gamma / 2 = 0.2886 is the exact constant of the exponential-integral asymptote. Raises
    ``PhysicsError`` below alpha t / r**2 = 25, where the approximation error exceeds
    about 1 % (roughly the first days of operation).
    """
    function = f"{context}ramey_time_function"
    _require_positive(function, error, code, time=time)
    _require_positive(function, error, code, diffusivity=diffusivity)
    _require_positive(function, error, code, radius=radius)
    fourier = diffusivity * time / radius**2
    ops.check(
        ops.logical_not(fourier < MIN_RAMEY_FOURIER),
        error,
        "{function}: alpha t / r**2 = {fourier}; expected >= {minimum}",
        code=code,
        function=function,
        fourier=fourier,
        minimum=MIN_RAMEY_FOURIER,
    )
    return ops.log(2 * ops.sqrt(fourier)) - EULER_GAMMA / 2


@ops.physics
def ramey_fluid_temperature(
    inlet_temperature: float,
    top_temperature: float,
    gradient: float,
    length: float,
    relaxation_length: float,
) -> float:
    """Return the temperature [K] of a fluid after flowing ``length`` down a geothermal gradient.

    Parameters
    ----------
    inlet_temperature : float
        Fluid temperature where it enters at the top [K].
    top_temperature, gradient : float
        Undisturbed rock temperature at the top [K] and its signed increase with depth [K/m].
    length : float
        Nonnegative vertical flow length [m].
    relaxation_length : float
        Positive A = m_dot cp R_total [m], with R_total the fluid-to-far-field resistance per
        unit length [m K/W].

    Returns
    -------
    float
        T(z) = T_top + G z - G A + (T_in - T_top + G A) exp(-z / A) [K].

    Notes
    -----
    Reference: Ramey (1962), Wellbore heat transmission, J. Petroleum Technology 14(4),
    427-435, equation for an injection well: the steady energy balance
    m_dot cp dT/dz = (T_rock(z) - T) / R_total with T_rock = T_top + G z, solved exactly for
    a constant resistance. The fluid's own conduction, friction heating and pressure work are
    neglected.
    """
    _require_positive("ramey_fluid_temperature", relaxation_length=relaxation_length)
    ops.check(
        ops.logical_not(length < 0),
        PhysicsError,
        "ramey_fluid_temperature: length = {length} m; expected >= 0",
        length=length,
    )
    offset = gradient * relaxation_length
    decay = ops.exp(-length / relaxation_length)
    rock = top_temperature + gradient * length
    return rock - offset + (inlet_temperature - top_temperature + offset) * decay


@ops.physics
def injected_volume(volume_flow: float, duration: float) -> float:
    """Return the liquid volume that flows through a well during a step.

    Parameters
    ----------
    volume_flow : float
        Liquid volume flow [m3/s], nonnegative.
    duration : float
        Step length [s], nonnegative.

    Returns
    -------
    float
        ``V = q dt`` [m3], exact for a flow that is constant over the step.

    Notes
    -----
    Definition of the volume flow; the cumulative injected volume of a balanced doublet
    equals its produced volume.
    """
    return volume_flow * duration


@ops.physics
def doublet_temperature_drop(
    injected: float, breakthrough: float, reservoir_temperature: float, injection_temperature: float
) -> float:
    """Return the drop of the produced temperature of a doublet after thermal breakthrough.

    Parameters
    ----------
    injected, breakthrough : float
        Cumulative injected volume [m3], nonnegative, and breakthrough volume V_B [m3], positive
        (``doublet_breakthrough_volume``).
    reservoir_temperature, injection_temperature : float
        Temperature carried by the produced water before the front arrives, and the
        injection temperature [K].

    Returns
    -------
    float
        ``dT = f(V / V_B) (T_res - T_inj)`` [K], with the cold share ``f`` of
        ``doublet_cold_fraction``.

    Notes
    -----
    Reference: Gringarten and Sauty (1975, J. Geophys. Res. 80(35), 4956-4962): the share of
    the flow on streamlines whose thermal travel time has passed arrives at the injection
    temperature. An upper bound of the decline: no heat recharge from confining beds.
    """
    return doublet_cold_fraction(injected / breakthrough) * (
        reservoir_temperature - injection_temperature
    )


@ops.physics
def doublet_breakthrough_time(breakthrough: float, volume_flow: float) -> float | None:
    """Return the time for a doublet's thermal front to reach the producer; ``None`` at no flow.

    Parameters
    ----------
    breakthrough : float
        Breakthrough volume V_B [m3] (``doublet_breakthrough_volume``).
    volume_flow : float
        Liquid volume flow Q [m3/s], nonnegative.

    Returns
    -------
    float or None
        ``t_B = V_B / Q`` [s], counted from the start of injection; ``None`` for zero flow.

    Notes
    -----
    Reference: Gringarten and Sauty (1975, J. Geophys. Res. 80(35), 4956-4962), at the current
    constant flow.
    """
    return ops.where(volume_flow != 0, breakthrough / volume_flow, None)


@ops.physics
def store_conductance(
    volume: float,
    conductivity: float,
    porosity: float,
    water_volumetric_heat_capacity: float,
    rock_heat_capacity: float,
    height: float,
    period: float,
) -> float:
    """Return the conduction conductance [W/K] of an aquifer store of injected water volume.

    Parameters
    ----------
    volume : float
        Injected water volume of the store [m3], nonnegative.
    conductivity : float
        Positive thermal conductivity of the aquifer and its surroundings [W/m/K].
    porosity : float
        Porosity in (0, 1) [-].
    water_volumetric_heat_capacity, rock_heat_capacity : float
        Volumetric heat capacities of the water and of the rock matrix [J/m3/K].
    height, period : float
        Positive aquifer thickness [m] and storage period [s].

    Returns
    -------
    float
        ``UA`` of ``cylinder_store_conductance`` for the diffusivity ``k / (rho c)_a`` and the
        thermal volume ``V (rho c)_w / (rho c)_a`` [W/K], with ``aquifer_volumetric_heat_capacity``
        for ``(rho c)_a``.

    Notes
    -----
    Reference: Bloemendal and Hartog (2018, Geothermics 71, 306-319) for the area-to-volume
    scaling of ATES losses; Carslaw and Jaeger (1959) for the conduction (see
    ``cylinder_store_conductance``).
    """
    aquifer = aquifer_volumetric_heat_capacity(
        porosity, water_volumetric_heat_capacity, rock_heat_capacity
    )
    return cylinder_store_conductance(
        conductivity,
        conductivity / aquifer,
        volume * water_volumetric_heat_capacity / aquifer,
        height,
        period,
    )


@ops.physics
def mix_store(
    volume: float, change: float, added_volume: float, added_change: float
) -> tuple[float, float]:
    """Return a fully mixed store after water is injected into it.

    Parameters
    ----------
    volume, change : float
        Store water volume [m3] and temperature change [K] before the injection.
    added_volume, added_change : float
        Injected volume [m3], nonnegative, and its temperature change [K] against the aquifer.

    Returns
    -------
    tuple of float
        ``(V + v, (V theta + v theta_i) / (V + v))``; the inputs unchanged for ``v = 0``.

    Notes
    -----
    Energy balance of an ideal mixture of one liquid at constant volumetric heat capacity,
    so the volumes weight the temperatures.

    Validity: volume and added_volume nonnegative, and their sum positive (the code divides by it,
    also for added_volume = 0); changes are real [K].
    Source: A first-law mixing balance; no published source is needed.
    """
    mixed = volume + added_volume
    blended = (volume * change + added_volume * added_change) / mixed
    return (
        ops.where(added_volume > 0, mixed, volume),
        ops.where(added_volume > 0, blended, change),
    )


@ops.physics
def store_relaxation(
    change: float,
    volume: float,
    conductance: float,
    duration: float,
    water_volumetric_heat_capacity: float,
) -> float:
    """Return a store's temperature change after conduction towards the aquifer temperature.

    Parameters
    ----------
    change : float
        Temperature change of the store against the aquifer [K].
    volume : float
        Store water volume [m3], nonnegative.
    conductance : float
        Conduction conductance of the store [W/K], nonnegative (``store_conductance``).
    duration : float
        Step length [s], nonnegative.
    water_volumetric_heat_capacity : float
        Volumetric heat capacity (rho c)_w of the water [J/m3/K].

    Returns
    -------
    float
        ``theta exp(-UA dt / ((rho c)_w V))`` [K]; zero for an empty store.

    Notes
    -----
    Reference: Incropera et al., Fundamentals of Heat and Mass Transfer, lumped capacitance
    method (``heat_transfer.relaxation_factor``) towards the aquifer temperature, whose change
    is zero. An empty store holds no excess heat.
    """
    factor = ops.where(
        volume == 0,
        0.0,
        heat_transfer.relaxation_factor(
            conductance, duration, water_volumetric_heat_capacity * volume
        ),
    )
    return heat_transfer.exponential_relaxation(change, 0.0, factor)


@ops.physics
def stored_heat(water_volumetric_heat_capacity: float, volume: float, change: float) -> float:
    """Return the excess heat of a water volume at a temperature change.

    Parameters
    ----------
    water_volumetric_heat_capacity : float
        Volumetric heat capacity (rho c)_w [J/m3/K].
    volume : float
        Water volume [m3].
    change : float
        Temperature change against the aquifer [K].

    Returns
    -------
    float
        ``E = (rho c)_w V theta`` [J].

    Notes
    -----
    Sensible heat of a liquid at constant volumetric heat capacity.

    Validity: water_volumetric_heat_capacity positive, volume nonnegative, change real; no division
    occurs. One uniform temperature change over the volume.
    Source: A first-law sensible-heat balance; no published source is needed.
    """
    return water_volumetric_heat_capacity * volume * change


@ops.physics
def aquifer_stored_energy(
    water_volumetric_heat_capacity: float,
    warm_volume: float,
    warm_change: float,
    cold_volume: float,
    cold_change: float,
) -> float:
    """Return the net excess heat of the warm and the cold store of a well pair.

    Parameters
    ----------
    water_volumetric_heat_capacity : float
        Volumetric heat capacity (rho c)_w [J/m3/K].
    warm_volume, cold_volume : float
        Water volumes of the stores [m3].
    warm_change, cold_change : float
        Temperature changes of the stores against the aquifer [K]; negative for a cold store.

    Returns
    -------
    float
        ``(rho c)_w (V_w theta_w + V_c theta_c)`` [J]; the cold store counts negative.

    Notes
    -----
    Sum of the sensible excess heats of the two stores at one volumetric heat capacity.

    Validity: water_volumetric_heat_capacity positive, both volumes nonnegative, changes real (the
    cold store is negative); no division occurs.
    Source: A first-law sensible-heat sum; no published source is needed.
    """
    return water_volumetric_heat_capacity * (warm_volume * warm_change + cold_volume * cold_change)


@ops.physics
def thermal_recovery(recovered_heat: float, charged_heat: float) -> float | None:
    """Return the thermal recovery efficiency of a store; ``None`` until heat has been charged.

    Parameters
    ----------
    recovered_heat, charged_heat : float
        Heat produced from and injected into the store, both relative to the aquifer
        temperature [J].

    Returns
    -------
    float or None
        ``eta = E_recovered / E_charged`` [-]; ``None`` while ``E_charged <= 0``.

    Notes
    -----
    Reference: Bloemendal and Hartog (2018, Geothermics 71, 306-319), definition of the
    thermal recovery efficiency of ATES.

    Validity: recovered_heat and charged_heat real; the value is ``None`` for charged_heat <= 0, so
    no division by zero occurs. The efficiency lies in [0, 1] for recovered_heat between 0 and
    charged_heat.
    """
    return ops.where(charged_heat > 0, recovered_heat / charged_heat, None)


@ops.physics
def borehole_loop_conductance(
    capacity_rate: float,
    count: float,
    depth: float,
    radius: float,
    spacing: float,
    conductivity: float,
    borehole_resistance: float,
    *,
    error: type[Exception] = PhysicsError,
    code: str | None = None,
    context: str = "",
) -> float:
    """Return the inlet-to-ground conductance of the loops of a borehole field.

    Parameters
    ----------
    capacity_rate : float
        Heat capacity rate ``m cp`` of the loop flow [W/K], nonnegative.
    count, depth, radius, spacing : float
        Number of boreholes [-], their depth, radius and spacing [m]; each borehole owns a
        ground cell of equivalent radius ``s / sqrt(pi)``.
    conductivity : float
        Positive ground conductivity [W/m/K].
    borehole_resistance : float
        Fluid-to-wall resistance R_b of a borehole [m K/W].
    error, code, context : optional
        Error class and message prefix of an invalid field geometry
        (``steady_flux_resistance``).

    Returns
    -------
    float
        ``K = eps C`` [W/K] with ``eps = 1 - exp(-UA / C)`` and
        ``UA = N H / (R_b + R_sf)``; zero for a stopped loop, whose geometry is not evaluated
        (a failed check of the cell is dropped there).

    Notes
    -----
    Plug flow along a loop against a constant ground temperature
    (``heat_transfer.ambient_effectiveness``), with the steady-flux ground resistance of
    Hellstrom (1991, Ground Heat Storage, Lund University).
    """
    cell = steady_flux_resistance(
        conductivity, radius, spacing / math.sqrt(math.pi), error=error, code=code, context=context
    )
    length = count * depth
    conductance = length / (borehole_resistance + cell)
    exchange = heat_transfer.ambient_effectiveness(conductance, capacity_rate) * capacity_rate
    return ops.where(capacity_rate == 0, 0.0, exchange)


@ops.physics
def borehole_field_surroundings_conductance(
    count: float,
    spacing: float,
    depth: float,
    conductivity: float,
    *,
    error: type[Exception] = PhysicsError,
    code: str | None = None,
    context: str = "",
) -> float:
    """Return the conductance [W/K] between a borehole field volume and the undisturbed ground.

    Parameters
    ----------
    count, spacing, depth : float
        Number of boreholes [-], their spacing [m] and depth [m]; the plan area is ``N s**2``.
    conductivity : float
        Positive ground conductivity [W/m/K].
    error, code, context : optional
        Error class and message prefix of an invalid geometry
        (``vertical_cylinder_conductance``).

    Returns
    -------
    float
        ``UA_s`` of ``vertical_cylinder_conductance`` for the plan diameter
        ``D = 2 sqrt(N s**2 / pi)`` [W/K].

    Notes
    -----
    Reference: Incropera et al., Fundamentals of Heat and Mass Transfer, table 4.1; the
    field is the vertical cylinder of equal plan area below an isothermal surface.
    """
    area = count * spacing**2
    diameter = 2 * ops.sqrt(area / math.pi)
    return vertical_cylinder_conductance(
        conductivity, depth, diameter, error=error, code=code, context=context
    )


@ops.physics
def borehole_field_capacity(
    volumetric_heat_capacity: float, count: float, spacing: float, depth: float
) -> float:
    """Return the heat capacity [J/K] of the lumped ground volume of a borehole field.

    Parameters
    ----------
    volumetric_heat_capacity : float
        Ground volumetric heat capacity (rho c)_g [J/m3/K].
    count, spacing, depth : float
        Number of boreholes [-], their spacing [m] and depth [m].

    Returns
    -------
    float
        ``C = (rho c)_g N s**2 H`` [J/K].

    Notes
    -----
    Volume of the field: one ``s`` by ``s`` cell of depth ``H`` per borehole.

    Validity: volumetric_heat_capacity, count, spacing and depth positive; no division occurs. A
    lumped field with a regular spacing.
    Source: A plain heat capacity of a volume; no published source is needed.
    """
    volume = count * spacing**2 * depth
    return volumetric_heat_capacity * volume


@ops.physics
def borehole_field_temperature_change(
    change: float,
    exchange: float,
    surroundings: float,
    inlet_temperature: float,
    undisturbed_temperature: float,
    duration: float,
    capacity: float,
) -> float:
    """Return the ground temperature change of a borehole field after one step.

    Parameters
    ----------
    change : float
        Mean ground temperature change theta against the undisturbed ground [K].
    exchange, surroundings : float
        Loop conductance K (``borehole_loop_conductance``) and conductance UA_s to the
        undisturbed ground [W/K].
    inlet_temperature, undisturbed_temperature : float
        Loop inlet temperature and undisturbed ground temperature [K].
    duration, capacity : float
        Step length [s] and field heat capacity C [J/K], positive.

    Returns
    -------
    float
        ``theta_eq + (theta - theta_eq) exp(-(K + UA_s) dt / C)`` [K] with
        ``theta_eq = K (T_in - T_u) / (K + UA_s)``.

    Notes
    -----
    Exact solution of ``C dtheta/dt = -Q - UA_s theta`` for a constant inlet over the step
    (Incropera et al., lumped capacitance method).

    Source: Incropera et al., Fundamentals of Heat and Mass Transfer, lumped capacitance method.
    """
    total = exchange + surroundings
    equilibrium = exchange * (inlet_temperature - undisturbed_temperature) / total
    factor = heat_transfer.relaxation_factor(total, duration, capacity)
    return heat_transfer.exponential_relaxation(change, equilibrium, factor)


@ops.physics
def ramey_rock_resistance(
    time: float,
    diffusivity: float,
    borehole_radius: float,
    conductivity: float,
    *,
    error: type[Exception] = PhysicsError,
    code: str | None = None,
    context: str = "",
) -> float:
    """Return the transient rock resistance [m K/W] of a well at an operating time.

    Parameters
    ----------
    time, diffusivity, borehole_radius : float
        Operating time [s], rock diffusivity [m2/s] and borehole radius [m]
        (``ramey_time_function``).
    conductivity : float
        Positive rock conductivity [W/m/K].
    error, code, context : optional
        Error class and message prefix of an operating time too early for the asymptote.

    Returns
    -------
    float
        ``R_r = f(t) / (2 pi k)`` [m K/W] with Ramey's time function ``f``.

    Notes
    -----
    Reference: Ramey (1962, Wellbore heat transmission, J. Petroleum Technology 14(4),
    427-435).
    """
    function = ramey_time_function(
        time, diffusivity, borehole_radius, error=error, code=code, context=context
    )
    return function / (2 * math.pi * conductivity)


@ops.physics
def ramey_relaxation_length(
    capacity_rate: float, borehole_resistance: float, rock_resistance: float
) -> float:
    """Return Ramey's relaxation length of the circuit fluid.

    Parameters
    ----------
    capacity_rate : float
        Heat capacity rate ``m cp`` [W/K], nonnegative.
    borehole_resistance, rock_resistance : float
        Fluid-to-wall and transient rock resistances per unit length [m K/W].

    Returns
    -------
    float
        ``A = m cp (R_b + R_r)`` [m].

    Notes
    -----
    Reference: Ramey (1962, J. Petroleum Technology 14(4), 427-435): steady energy balance
    ``m cp dT/dz = (T_rock - T) / R``.
    """
    return capacity_rate * (borehole_resistance + rock_resistance)


def _travel_time_residual(theta, volume_ratio):
    """Return the dipole travel time at ``theta`` minus ``volume_ratio`` [-]."""
    return _dipole_travel_time(theta) - volume_ratio


def _dipole_travel_time(theta):
    """Return t(theta) / t_B = 3 (sin theta - theta cos theta) / sin(theta)**3 [-].

    Below ``_SMALL_ANGLE`` the difference uses its Taylor series
    theta**3/3 - theta**5/30 + theta**7/840 - theta**9/45360 to avoid cancellation. Both
    forms are evaluated and ``where`` selects one.
    """
    square = theta * theta
    series = theta**3 * (1 / 3 - square / 30 + square**2 / 840 - square**3 / 45360)
    direct = ops.sin(theta) - theta * ops.cos(theta)
    difference = ops.where(theta < _SMALL_ANGLE, series, direct)
    return 3 * difference / ops.sin(theta) ** 3


def _require_positive(function, error=PhysicsError, code=None, **values):
    """Raise ``error`` with ``code`` unless every value is positive."""
    for name, value in values.items():
        ops.check(
            ops.logical_not(ops.logical_or(ops.isnan(value), value <= 0)),
            error,
            "{function}: {name} = {value}; expected a positive value",
            code=code,
            function=function,
            name=name,
            value=value,
        )
