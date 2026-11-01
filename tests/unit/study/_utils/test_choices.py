"""The variables of a search: the choices of the case, or the list of a call."""

import gemini as gm
from gemini.study._utils.choices import STRUCTURE, from_choices, split
from tests.fixtures.errors import raises
from tests.unit.study.conftest import shallow_case, shallow_plant


def test_the_choices_of_the_case_are_two_variables():
    """The doublets as a count, the depth as a length."""
    found = from_choices(shallow_case())
    assert [item["parameter"] for item in found] == ["doublets", "depth"]
    assert found[1]["lower"].si == 1000 and found[1]["upper"].si == 2000


def test_the_counts_and_the_continuous_variables_are_split():
    """Every integer from lower to upper; the others in SI."""
    plant, case = shallow_plant(), shallow_case()
    counts, names, bounds = split(plant, case, from_choices(case))
    assert counts == [1, 2, 3] and names == ["depth"] and bounds == [(1000, 2000)]


def test_without_the_count_the_plant_keeps_its_doublets():
    """The counts are ``[None]``."""
    case = shallow_case()
    counts, _, _ = split(shallow_plant(), case, from_choices(case)[1:])
    assert counts == [None]


def test_a_case_without_choices_has_none():
    """``missing_value`` naming ``choices``."""
    case = shallow_case().model_copy(update={"choices": None})
    with raises(gm.errors.ValidationError, "missing_value") as refused:
        from_choices(case)
    assert refused.value.path == "choices"


def test_a_count_range_the_wrong_way_round_is_refused():
    """Lower above upper."""
    item = {"path": "size", "parameter": "doublets", "lower": 3, "upper": 1}
    with raises(gm.errors.ValidationError, "out_of_bounds", match=STRUCTURE):
        split(shallow_plant(), shallow_case(), [item])
