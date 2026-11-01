"""Annualised system cost."""

from gemini.evaluate._utils.levelised import annualised
from gemini.evaluate._utils.outcome import reported


def annualised_cost(plant, problem, results, discount_rate=None, lifetime=None, on_error="raise"):
    """Return the annualised system cost [currency/year]: ``capex / A + opex``.

    ``A`` is the annuity factor of ``lcoh``, the sum over the lifetime years of
    ``1 / (1 + discount_rate) ** t``; ``capex`` and ``opex`` are those of this package, with the
    yearly cost as scaled from the run, constant over the lifetime.

    Parameters
    ----------
    plant : Module
        The plant of the run.
    problem : Problem
        Its assumptions give the prices and, when not given below, the rate and lifetime.
    results : Results
        The finished run of the plant.
    discount_rate : float, optional
        Real discount rate per year [-]; ``assumptions.discount_rate`` when ``None``.
    lifetime : int, optional
        Years of operation; ``assumptions.lifetime_years`` when ``None``.
    on_error : {"raise", "record"}, optional
        A value the inputs cannot give raises; ``"record"`` makes it ``None`` with a ``reason``.

    Returns
    -------
    Value
        A ``gm.units.Quantity`` in SI, with the parts of the result in ``parts`` (``to_plain``
        gives the JSON). ``{value, unit, capex, opex, annuity_factor, discount_rate,
        lifetime_years}``, the last
        five each a value. A plant that declares no cost has no value.
    """
    return reported(
        on_error,
        "currency/yr",
        lambda: annualised(
            problem.apply_site(plant), problem, results, (discount_rate, lifetime), on_error
        ),
    )
