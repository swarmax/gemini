"""Reading, writing and describing the ``uncertainty`` that sits next to a value."""

import pytest

from gemini.case._utils import declared
from gemini.errors import ValidationError


def test_extract_takes_the_declarations_out_and_keeps_the_input():
    """A bare number is left in place of its node; the input dict is untouched."""
    data = {
        "assumptions": {
            "finance": {
                "discount_rate": {"value": 0.05, "uncertainty": {"kind": "uniform"}},
                "opex": {"gas": {"value": 40, "unit": "EUR/MWh", "uncertainty": {"kind": "x"}}},
            }
        }
    }
    clean, found = declared.extract(data)
    assert clean["assumptions"]["finance"]["discount_rate"] == 0.05
    assert clean["assumptions"]["finance"]["opex"]["gas"] == {"value": 40, "unit": "EUR/MWh"}
    assert found["assumptions.finance.opex.gas"] == ({"kind": "x"}, "EUR/MWh")
    assert found["assumptions.finance.discount_rate"][1] is None
    assert "uncertainty" in data["assumptions"]["finance"]["discount_rate"]


def test_extract_refuses_other_sections_and_non_numbers():
    """Time, demand, choices and constraints cannot carry one; a profile cannot either."""
    with pytest.raises(ValidationError) as caught:
        declared.extract({"choices": {"depth": {"uncertainty": {}}}})
    assert caught.value.path == "choices.depth.uncertainty"
    with pytest.raises(ValidationError):
        declared.extract(
            {"environment": {"air": {"temperature": {"file": "a", "uncertainty": {}, "value": 1}}}}
        )


def test_with_schema_adds_the_key_to_numbers_only():
    """A quantity form gains the optional key; the dimensionless number gains a bare form."""
    number = {"type": "number"}
    form = {"type": "object", "required": ["value", "unit"], "properties": {"value": number}}
    found = declared.with_schema({"anyOf": [{"type": "number"}, form]})
    assert "uncertainty" in found["anyOf"][1]["properties"]
    assert found["anyOf"][2]["required"] == ["value", "uncertainty"]
