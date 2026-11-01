"""Annual operating cost of a plant run."""

from gemini.evaluate._utils.cost import yearly_cost
from gemini.evaluate._utils.outcome import reported
from gemini.run._utils.apply import apply_case


def opex(plant, case, results, on_error="raise"):
    """Return the annual operating cost of a plant run.

    The sum of the fixed opex of each kind of equipment [currency/yr], its share
    ``opex.fixed[kind]`` of the capex of that kind, the yearly bill of the grid electricity, the
    fuel, the waste and the chemicals, and the CO2 emitted per year at ``opex.co2`` when the case
    gives it. The run is scaled to a year. A price along the demand is integrated over the run:
    the power of each step times its price. A share the case lacks for a kind the plant uses
    raises ``missing_assumption`` naming ``assumptions.finance.opex.fixed.<kind>``.

    Parameters
    ----------
    plant : Module
        The plant whose modules declare costs; its design values are those with the case applied.
    case : Case
        Its finance gives the prices, needed only for an energy that the run buys; a missing
        needed price raises ``ValidationError`` (code ``missing_assumption``). Co-produced gas
        costs nothing.
    results : Results
        A finished run of the plant.
    on_error : {"raise", "record"}, optional
        A value the inputs cannot give raises; ``"record"`` makes it ``None`` with a ``reason``.

    Returns
    -------
    Value
        A ``gm.units.Quantity`` in SI, with the parts of the result in ``parts`` (``to_plain``
        gives the JSON). ``{value, unit, components, fixed_by_kind}`` with ``unit`` the currency
        per year, ``components`` ``{fixed, electricity, fuel, waste, chemical}`` and ``co2`` with a
        price for it, and ``fixed_by_kind`` the fixed opex of each kind of equipment, each a value
        in that unit. With no equipment and ``on_error="record"``, ``value`` is ``None`` with a
        ``reason``, and only the bills are given.
    """
    return reported(
        on_error,
        "currency/yr",
        lambda: yearly_cost(apply_case(plant, case), case, results, on_error),
    )
