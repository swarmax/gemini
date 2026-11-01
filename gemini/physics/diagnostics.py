"""Health-scoring relations shared by the modules: drift, bounded score, margin, limit test.

These are plain ratio formulas, not heat or flow physics; they sit here so that every module
that scores a measurement against a prediction uses the same expression.
"""

from gemini import ops

DRIFT_FLOOR = 1e-12
"""Smallest prediction magnitude used as a drift denominator, so a zero prediction is finite."""


@ops.physics
def relative_drift(measured: float, predicted: float) -> float:
    """Return the relative deviation of a measurement from its prediction.

    Parameters
    ----------
    measured, predicted : float
        Measured and predicted value, in the same unit.

    Returns
    -------
    float
        ``(measured - predicted) / max(|predicted|, DRIFT_FLOOR)`` [-]; finite for a zero
        prediction.

    Notes
    -----
    Plain relative error; the floor ``DRIFT_FLOOR`` only avoids a division by zero.

    Validity: Valid for any real measured and predicted values in one unit; the divisor is at least
    DRIFT_FLOOR, so it is never zero.
    Source: A plain definition, no published source.
    """
    return (measured - predicted) / ops.maximum(ops.abs(predicted), DRIFT_FLOOR)


@ops.physics
def bounded_score(ratio: float) -> float:
    """Return a ratio clipped to [0, 1], a health score.

    Parameters
    ----------
    ratio : float
        Measured over reference value [-].

    Returns
    -------
    float
        ``min(1, max(0, ratio))`` [-].

    Notes
    -----
    One is a healthy unit, zero a failed one; no published source, a scoring convention.

    Validity: Valid for any real ratio; the result is in [0, 1] by construction. No division occurs.
    """
    return ops.minimum(1, ops.maximum(0, ratio))


@ops.physics
def remaining_margin(ratio: float) -> float:
    """Return the margin left before a ratio reaches one.

    Parameters
    ----------
    ratio : float
        Used over allowed value [-], for example a drift over its threshold.

    Returns
    -------
    float
        ``max(0, 1 - ratio)`` [-]; one for no use, zero at or beyond the limit.

    Notes
    -----
    Scoring convention without a published source.

    Validity: Valid for any real ratio, normally nonnegative; the result is in [0, 1] for ratio >=
    0. No division occurs.
    """
    return ops.maximum(0, 1 - ratio)


@ops.physics
def below_limit(ratio: float, threshold: float) -> bool:
    """Return whether a ratio fell by more than the threshold.

    Parameters
    ----------
    ratio : float
        Measured over reference value [-], one when healthy.
    threshold : float
        Allowed fractional loss [-], in (0, 1].

    Returns
    -------
    bool
        ``ratio < 1 - threshold``.

    Notes
    -----
    Alarm convention for a decline or fouling test, without a published source.

    Validity: ratio is real, normally nonnegative; threshold in (0, 1] (a value outside this range
    is not checked). No division occurs.
    """
    return ratio < 1 - threshold


@ops.physics
def performance_ratio(measured: float, reference: float) -> float:
    """Return a measured performance over its reference value, ``measured / reference`` [-].

    Parameters
    ----------
    measured, reference : float
        Two values of one quantity, for example an apparent and a design conductance [W/K], a
        measured and a design productivity index [m3/s/Pa] or a pressure drop and its limit [Pa].

    Returns
    -------
    float
        The ratio [-]; valid for a nonzero reference. A plain definition, no published source.
    """
    return measured / reference
