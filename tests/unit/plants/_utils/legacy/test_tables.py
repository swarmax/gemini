"""Old-format name tables and property converters."""

import pytest

from gemini.plants._utils.legacy import tables


def test_tables_are_centralised():
    """Known old node, port and module names map in the legacy package only."""
    assert tables.PORTS["esp"]["out"] == "fluid_out"
    assert tables.NODE_PATHS["esp_1ee3"] == "doublet.esp"
    assert tables.MODULE_CLASSES["heat_exchanger"].__name__ == "HeatExchanger"
    assert set(tables.CONVERTERS) <= set(tables.MODULE_CLASSES)


def test_esp_converter_uses_si():
    """Flow limits [m3/h] and the correction offset [bar] become SI values."""
    params = tables.esp_params_from_gemini(
        {
            "esp_no_stage": 15,
            "esp_head_coeff": "1;2",
            "esp_power_coeff": [0, 0],
            "esp_min_flow": 36,
            "esp_correction_factor": "1;0.5",
        }
    )
    assert params["head_coefficients"] == [1.0, 2.0]
    assert params["minimum_flow"] == pytest.approx(0.01)
    assert params["correction_factors"] == (1.0, 50000.0)


def test_trajectory_file_is_read_as_utf8_with_bom(tmp_path):
    """A trajectory CSV saved with a byte-order mark keeps its first column name."""
    (tmp_path / "trajectory.csv").write_bytes(
        "﻿MD;TVD;ID;material;roughness\n0;0;0.1778;ST;2e-05\n1000;1000;0.1778;ST;2e-05\n".encode()
    )
    params = tables.injectionwell_params_from_gemini(
        {"injectionwell_trajectory_file": "trajectory.csv", "injectionwell_soil_temperature": 15},
        base_path=tmp_path,
    )
    assert params["soil_temperature"] == pytest.approx(288.15)
    assert params["section_length"] == [1000.0]
