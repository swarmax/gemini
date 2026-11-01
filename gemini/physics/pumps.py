"""Pump relations: the TNO R11363 power polynomial, affinity-law curves, efficiencies.

The ESP and line-shaft pumps use the TNO R11363 power polynomial on the historical US basis
(``power``, which the doublet design reads too; the head polynomial and the ESP efficiency are in
``gemini/modules/pumps/_physics.py``). The centrifugal pump uses a quadratic head curve in SI with
a parabolic efficiency (``centrifugal_head``, ``parabolic_efficiency``). The shared relations
are the speed ratio, the hydraulic and shaft power and the operating window.
"""

from gemini import ops, units

from . import constants

POLYNOMIAL_COEFFICIENT_COUNT = 6
"""Number of ascending coefficients of the degree-5 TNO head and power polynomials."""


RUNOUT_LOAD = 2
"""Flow over the speed-scaled best-efficiency flow [-] at which the centrifugal curve ends."""


CENTRIFUGAL_HEAD_COEFFICIENT_COUNT = 3
"""Number of coefficients ``c0, c1, c2`` of the quadratic centrifugal head curve."""


@ops.physics
def power(volume_flow, frequency, stages, coefficients):
    """Return power [W] from flow [m3/s], frequency [Hz], stages and bhp coefficients.

    The polynomial sum(c_i q^i) uses q in bbl/day and gives bhp per stage at 60 Hz; power
    scales with the cube of the frequency ratio.

    Valid for the fitted flow range of the coefficients and positive frequency and stages. The
    affinity law follows Takacs, Electrical Submersible Pumps Manual (2009); the polynomial
    form is the TNO R11363 pump correlation. The builtin ``sum`` over the coefficients is kept:
    it works on floats, arrays and traced values.
    """
    q = units.m3s_to_bbl_per_day(volume_flow)
    value = stages * (frequency / constants.ESP_REFERENCE_FREQUENCY) ** 3
    value *= sum(c * q**i for i, c in enumerate(coefficients))
    return units.bhp_to_w(value)


def constant_head_curves(design_head, efficiency):
    """Return the head and power coefficients of a pump with one head at its design efficiency.

    Parameters
    ----------
    design_head : float
        Head the pump adds at any flow [Pa], at the reference frequency.
    efficiency : float
        Hydraulic efficiency [-], positive.

    Returns
    -------
    tuple of list of float
        ``(head, power)`` coefficients of ``head`` and ``power`` for one stage: a constant head and
        a power of ``Q H / eta`` on the US basis.

    Notes
    -----
    A pump sized from a design point, without a catalogue curve: the head is the one the design
    needs at any flow and the power is the hydraulic power over the efficiency, the relation of
    ``hydraulic_power``.

    Validity: One stage, at the reference frequency of the ESP.
    Source: The hydraulic power of a pump, Karassik et al., Pump Handbook.
    """
    head_curve = [units.pa_to_ft_head(design_head)] + [0.0] * (POLYNOMIAL_COEFFICIENT_COUNT - 1)
    power_per_flow = units.w_to_bhp(design_head / efficiency) / units.m3s_to_bbl_per_day(1.0)
    power_curve = [0.0, power_per_flow] + [0.0] * (POLYNOMIAL_COEFFICIENT_COUNT - 2)
    return head_curve, power_curve


@ops.physics
def speed_ratio(frequency, rated_frequency):
    """Return the speed ratio of a variable-speed pump.

    Parameters
    ----------
    frequency, rated_frequency : float
        Drive frequency and the frequency of the catalogue curves [Hz], positive.

    Returns
    -------
    float
        ``s = f / f_rated`` [-].

    Notes
    -----
    Pump speed is proportional to the supply frequency of an induction motor (Takacs,
    Electrical Submersible Pumps Manual, 2009, affinity laws).
    """
    return frequency / rated_frequency


@ops.physics
def centrifugal_head(flow, speed, coefficients):
    """Return the pressure rise of a centrifugal pump from its quadratic curve and the speed.

    Parameters
    ----------
    flow : float
        Volume flow Q [m3/s], nonnegative.
    speed : float
        Speed ratio s [-], from ``speed_ratio``.
    coefficients : sequence of float
        ``c0, c1, c2`` [Pa, Pa s/m3, Pa s2/m6] of the curve ``H = c0 + c1 Q + c2 Q^2`` at rated
        speed.

    Returns
    -------
    float
        ``H = c0 s^2 + c1 s Q + c2 Q^2`` [Pa].

    Notes
    -----
    The affinity laws Q ~ s and H ~ s^2 applied to the rated-speed curve; valid for speed
    ratios of about 0.5 to 1.1 (Karassik et al., Pump Handbook, 4th ed., chapter 2).
    """
    c0, c1, c2 = coefficients
    return c0 * speed**2 + c1 * speed * flow + c2 * flow**2


@ops.physics
def best_efficiency_ratio(flow, speed, best_efficiency_flow):
    """Return the flow relative to the speed-scaled best-efficiency flow.

    Parameters
    ----------
    flow : float
        Volume flow Q [m3/s].
    speed : float
        Speed ratio s [-], positive.
    best_efficiency_flow : float
        Best-efficiency flow at rated speed [m3/s], positive.

    Returns
    -------
    float
        ``x = Q / (s Q_bep)`` [-]; one at the best-efficiency point.

    Notes
    -----
    The best-efficiency flow scales with speed (affinity law Q ~ s).

    Source: The affinity laws, Karassik et al., Pump Handbook, 4th ed., chapter 2.
    """
    return flow / (speed * best_efficiency_flow)


@ops.physics
def parabolic_efficiency(best_efficiency, load):
    """Return the hydraulic efficiency of the parabola through the origin.

    Parameters
    ----------
    best_efficiency : float
        Maximum efficiency [-] at the best-efficiency flow.
    load : float
        Flow over the speed-scaled best-efficiency flow ``x`` [-], from
        ``best_efficiency_ratio``; the curve is meaningful for 0 <= x < 2.

    Returns
    -------
    float
        ``eta = eta_bep x (2 - x)`` [-].

    Notes
    -----
    Speed-scaled quadratic efficiency curve of Ulanicki, Kahler and Coulbeck (2008), Modeling the
    efficiency and power characteristics of a pump group, J. Water Resour. Plann. Manage.
    134(1), 88-93. The 2 is the shape of the parabola (zero slope at x = 1).

    Validity: best_efficiency in (0, 1] and load in [0, 2), where the curve is nonnegative; no
    division occurs.
    """
    return best_efficiency * load * (2 - load)


@ops.physics
def hydraulic_power(flow, head):
    """Return the power given to the liquid by a pump.

    Parameters
    ----------
    flow : float
        Volume flow Q [m3/s].
    head : float
        Pressure rise H [Pa].

    Returns
    -------
    float
        ``P_hyd = Q H`` [W].

    Notes
    -----
    Karassik et al., Pump Handbook, 4th ed., chapter 2 (water horsepower).

    Validity: flow and head nonnegative for a pump; no division occurs. Incompressible liquid.
    """
    return flow * head


def speed_scaled_flow(flow, speed):
    """Return a flow limit of a pump at a speed ratio [m3/s].

    Parameters
    ----------
    flow : float
        Limit at rated speed [m3/s].
    speed : float
        Speed ratio [-].

    Notes
    -----
    The flow range of the fitted curves scales with speed (affinity law Q ~ s; Takacs,
    Electrical Submersible Pumps Manual, 2009).
    """
    return flow * speed


@ops.physics
def is_in_operating_window(flow, minimum_flow, maximum_flow, speed):
    """Return whether a flow lies inside the speed-scaled operating window of a pump.

    Parameters
    ----------
    flow : float
        Volume flow [m3/s].
    minimum_flow, maximum_flow : float
        Window limits at rated speed [m3/s].
    speed : float
        Speed ratio [-].

    Returns
    -------
    bool
        ``s Q_min <= Q <= s Q_max``.

    Notes
    -----
    The recommended operating range scales with speed (affinity law Q ~ s; Takacs, Electrical
    Submersible Pumps Manual, 2009).
    """
    return ops.logical_and(minimum_flow * speed <= flow, flow <= maximum_flow * speed)


@ops.physics
def intake_gas_volume_fraction(liquid_density, gas_density, gas_mass_fraction):
    """Return the free-gas volume fraction [-] of a mixture at the pump intake.

    Parameters
    ----------
    liquid_density, gas_density : float
        Phase densities [kg/m3] at the intake pressure and temperature, nonnegative gas density.
    gas_mass_fraction : float
        Free-gas mass fraction ``x`` [-], in ``[0, 1)``.

    Returns
    -------
    float
        Gas volume over total volume, ``x rho_l / (x rho_l + (1 - x) rho_g)``; it is ``(x / rho_g)
        / (x / rho_g + (1 - x) / rho_l)`` written without a division by the gas density, so a
        near-zero intake pressure gives a fraction near one.

    Notes
    -----
    Homogeneous (no-slip) mixture at intake conditions, the volume basis of the mixture density
    used for the stream volume flow. Source: a plain volume balance; no published source is needed.

    Validity: positive liquid density; undefined for no gas and zero gas density together.
    """
    gas = gas_mass_fraction * liquid_density
    return gas / (gas + (1 - gas_mass_fraction) * gas_density)
