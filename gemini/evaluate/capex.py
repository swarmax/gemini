"""Investment of a plant."""

from gemini.evaluate._utils.cost import investment
from gemini.evaluate._utils.outcome import reported
from gemini.run._utils.apply import apply_case


def capex(plant, case, on_error="raise"):
    """Return the investment of a plant: the sum of the capex of its equipment, per module.

    A module that is equipment declares a kind (``gemini.case._utils.kinds.EQUIPMENT_KINDS``) and
    a ``capex(finance)``: the capex factor of its kind in ``case.assumptions.finance.capex`` times
    its own size. A factor the case lacks for a kind the plant uses raises ``ValidationError``
    (code ``missing_assumption``) naming ``assumptions.finance.capex.<kind>``; nothing is
    estimated. The design values are those of the plant with the case applied.

    Parameters
    ----------
    plant : Module
        The plant whose modules declare costs.
    case : Case
        Its finance gives the capex factors, the currency label and the price year.
    on_error : {"raise", "record"}, optional
        A value the inputs cannot give raises; ``"record"`` makes it ``None`` with a ``reason``.

    Returns
    -------
    Value
        A ``gm.units.Quantity`` in SI, with the parts of the result in ``parts`` (``to_plain``
        gives the JSON). ``{value, unit, modules, price_year}``: ``value`` is the investment in
        the currency of the case (``unit``), ``modules`` maps the path of each module that is
        equipment to its capex, a value with its ``kind``, and ``price_year`` is a value in ``-``
        when the case gives it. A plant with no equipment has no value.
    """
    return reported(
        on_error,
        "currency",
        lambda: investment(apply_case(plant, case), case, on_error),
    )
