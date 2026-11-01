"""Production well traversal and ESP splitting across a trajectory section."""

import numpy as np
import pytest

from gemini.compiler.graph import GraphCache, run
from gemini.modules.wells import ProductionWell
from gemini.plants._utils.legacy import tables as mapping
from gemini.types.flows import Stream
from tests.fixtures import OLD_PROJECT
from tests.fixtures.equivalence import assert_function_matches, assert_module_matches


def test_split_esp_traversal():
    """Split at 600 m inside a section; pumping raises the resulting wellhead pressure."""
    c = ProductionWell().set_params(
        "",
        mapping.productionwell_params_from_gemini(
            mapping.from_property(OLD_PROJECT / "production_well_c774.param"),
            esp_property=mapping.from_property(OLD_PROJECT / "esp_1ee3.param"),
        ),
    )
    stream = Stream(m_dot=40, T=353.15, p=25e6)
    intake = c.intake_conditions(stream)
    out = c.wellhead_from_discharge(intake.with_(p=intake.p + 3e6))
    passive = c.wellhead_from_discharge(intake)
    assert out.p - passive.p == pytest.approx(3e6)
    assert out.m_dot == stream.m_dot
    assert len(c.corrosion_profile(stream, {"co2_fraction": 0.1}, model="DLM")) == len(
        c.pipe_path.sections
    )
    assert len(c.erosion_check(stream)["velocity"]) == len(c.pipe_path.sections)


def _well(**changes):
    return ProductionWell().set_params(
        "",
        mapping.productionwell_params_from_gemini(
            mapping.from_property(OLD_PROJECT / "production_well_c774.param"),
            esp_property=mapping.from_property(OLD_PROJECT / "esp_1ee3.param"),
        )
        | changes,
    )


def _outlet(stream):
    return dict(m_dot=stream.m_dot, T=stream.T, p=stream.p)


def test_traversals_match_on_arrays():
    """Intake, wellhead and discharge conditions on arrays equal one call per row."""
    well = _well(correction_factors=(0.99, 1000.0))
    rows = [(40.0, 353.15, 25e6), (-10.0, 340.0, 20e6), (0.0, 353.15, 25e6), (5.0, 300.0, 1e6)]

    def stream(m_dot, T, p):
        return Stream(m_dot=m_dot, T=T, p=p)

    def intake(m_dot, T, p):
        return _outlet(well.intake_conditions(stream(m_dot, T, p)))

    def wellhead(m_dot, T, p):
        return _outlet(well.wellhead_from_discharge(stream(m_dot, T, p)))

    def discharge(m_dot, T, p):
        return _outlet(well.discharge_from_wellhead(stream(m_dot, T, p)))

    for function in (intake, wellhead, discharge):
        assert_function_matches(function, rows)


def test_production_well_traces_with_its_section_profiles():
    """The per-section lists are vector outputs: the module traces and equals one call per row."""
    rows = [
        {"bottom_in": Stream(m_dot=40.0, T=353.15, p=25e6)},
        {"bottom_in": Stream(m_dot=10.0, T=340.0, p=20e6)},
        {"bottom_in": Stream(m_dot=25.0, T=300.0, p=5e6)},
    ]
    assert_module_matches(_well(), rows)
    traced = run(
        _well(),
        {
            "bottom_in": Stream(
                m_dot=np.array([40.0, 10.0]), T=np.array([353.15, 340.0]), p=np.array([25e6, 20e6])
            )
        },
    )
    assert traced.breaks == [] and traced.outputs["section_pressure"].shape[0] == 2


def test_another_esp_depth_and_path_length_reuse_the_graph():
    """The ESP depth and the section lengths are graph inputs: a new value traces nothing."""
    cache = GraphCache()
    first, other = _well(), _well()
    other.esp_depth = first.esp_depth - 50
    other.section_length = [length * 1.1 for length in first.section_length]
    for well in (first, other):
        cache.graph(well, {name: well.fluid for name in well._fed_inlets()})
    assert cache.traces == 1
    assert_module_matches(other, [{"bottom_in": Stream(m_dot=40.0, T=353.15, p=25e6)}])
