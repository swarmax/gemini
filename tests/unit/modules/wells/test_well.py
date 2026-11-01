"""Shared well traversal, correction and direction checks."""

import numpy as np
import pytest

import gemini as gm
from gemini.modules.wells import InjectionWell, ProductionWell
from gemini.types.flows import Stream
from scripts.legacy import tables as mapping
from tests.fixtures import OLD_PROJECT
from tests.fixtures.errors import raises


def production_well():
    """Return the example production well."""
    return ProductionWell().set_params(
        "",
        mapping.productionwell_params_from_gemini(
            mapping.from_property(OLD_PROJECT / "production_well_c774.param"),
            esp_property=mapping.from_property(OLD_PROJECT / "esp_1ee3.param"),
        ),
    )


def test_both_wells_share_the_design_parameters_in_order():
    """The shared base declares the same nine parameters first in both wells."""
    shared = [
        "section_length",
        "section_inclination",
        "section_diameter",
        "section_roughness",
        "friction_correlation",
        "two_phase_friction_correlation",
        "correction_factors",
        "soil_temperature",
        "heat_transfer_coefficient",
    ]
    assert list(dict(InjectionWell().named_parameters())) == shared
    assert list(dict(ProductionWell().named_parameters()))[:9] == shared


def test_correction_applies_the_affine_pressure_factors():
    """The corrected outlet uses ``a * p + b`` and the traversal temperature."""
    well = production_well()
    well.correction_factors = (1.0, 1000.0)
    stream = Stream(m_dot=40, T=353.15, p=25e6)
    result = well.traverse(stream, well.pipe_path.total_length, 0, "up")
    corrected = well.corrected(stream, result)
    assert corrected.p == result.p_out + 1000.0
    assert corrected.T == result.T_out
    assert corrected.m_dot == stream.m_dot


def test_traversal_direction_must_match_the_depth_interval():
    """Upward traversal from shallow to deep is rejected with both depths in the message."""
    well = production_well()
    with pytest.raises(gm.errors.PhysicsError, match="conflicts with direction up"):
        well.traverse(Stream(m_dot=40, T=353.15, p=25e6), 0, 100, "up")


def test_esp_split_needs_a_configured_depth():
    """Splitting at the ESP without an ESP depth inside the path is a configuration error."""
    well = production_well()
    well.esp_depth = None
    with raises(gm.errors.ValidationError, "invalid_design", match="esp_depth"):
        well.intake_conditions(Stream(m_dot=40, T=353.15, p=25e6))


def test_esp_split_needs_the_depth_inside_the_path():
    """An ESP below the bottom of the path is a configuration error that names the depth."""
    well = production_well()
    well.esp_depth = well.total_length + 1
    with raises(gm.errors.ValidationError, "invalid_design", match="esp_depth"):
        well.intake_conditions(Stream(m_dot=40, T=353.15, p=25e6))


def test_traversal_direction_check_runs_on_depths_not_flows():
    """A downward interval is accepted going down and rejected going up, for any flow."""
    well = production_well()
    stream = Stream(
        m_dot=np.array([40.0, 0.0]), T=np.array([353.15, 353.15]), p=np.array([25e6, 25e6])
    )
    result = well.traverse(stream, 0, 100, "down")
    assert result.p_out.shape == (2,)
    with pytest.raises(gm.errors.PhysicsError, match="conflicts with direction up"):
        well.traverse(stream, 0, 100, "up")
