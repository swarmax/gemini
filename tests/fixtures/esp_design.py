"""The ESP values that were defaults before they became a design decision."""

ESP_DESIGN = {
    "esp.pump_type": "unspecified",
    "esp.motor_efficiency": 1.0,
    "esp.minimum_flow": {"value": 0, "unit": "m3/s"},
    "esp.maximum_flow": {"value": 1, "unit": "m3/s"},
    "esp.best_efficiency_flow": {"value": 0.04, "unit": "m3/s"},
    "esp.drift_threshold": 0.1,
    "esp.correction_factors": [1.0, 0.0],
}
"""What a designed doublet leaves to its plant, under ``esp.``: no flow window, 0.04 m3/s best flow.

The setting depth is not here: the design derives it.
"""

ESP_MODULE = {name.removeprefix("esp."): value for name, value in ESP_DESIGN.items()} | {
    "setting_depth": {"value": 0, "unit": "m"}
}
"""The same values for an ESP set on its own, with the setting depth it had by default."""
