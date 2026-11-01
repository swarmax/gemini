"""The best trial of a search: a value with its plant."""

import gemini as gm
from gemini.study._utils.best import Best


def test_the_plant_is_a_key_and_its_plant_dict_in_the_json():
    """``best["plant"]`` is the plant, the rest are parts; the JSON holds its plant dict."""
    plant = gm.Plant("Empty")
    best = Best(3.0, "W", None, {"parameters": {}}, plant)
    assert best["plant"] is plant and best["parameters"] == {}
    assert best.to_dict()["plant"] == plant.to_dict()


def test_a_conversion_keeps_the_plant():
    """Only the unit changes."""
    plant = gm.Plant("Empty")
    best = Best(3000.0, "W", None, {}, plant).to("kW")
    assert best.value == 3.0 and best.plant is plant
