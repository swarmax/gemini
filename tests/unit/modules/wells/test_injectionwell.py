"""Injection well sign convention and mass conservation."""

import numpy as np

from gemini.compiler.graph import run
from gemini.modules.wells import InjectionWell
from gemini.types.flows import Stream
from gemini.types.fluid import BRINE as DEFAULT_FLUID
from gemini.units import Quantity
from scripts.legacy import tables as mapping
from tests.fixtures import OLD_PROJECT, si
from tests.fixtures.equivalence import assert_function_matches, assert_module_matches
from tests.fixtures.reading import reading


def test_injection_flow_sign_and_pressure():
    """Ports conserve mass while the internal DPDT correlation retains its negative sign."""
    c = si.set_params(
        InjectionWell(),
        "",
        mapping.injectionwell_params_from_gemini(
            mapping.from_property(OLD_PROJECT / "injection_well_a06b.param")
        ),
    )
    result = c(
        wellhead_in=Stream(m_dot=Quantity(40, "kg/s"), T=Quantity(300, "K"), p=Quantity(5e6, "Pa"))
    )
    out, streams = reading(result), result.outlets
    assert out.friction_pressure_drop < 0 and out.gravity_pressure_drop > 0
    assert streams["bottom_out"].m_dot == 40
    assert out.bottomhole_pressure > 5e6


def test_corrosion_profile_uses_injection_flow_sign():
    """Positive surface flow and negative downhole flow describe the same injection state."""
    well = si.set_params(
        InjectionWell(),
        "",
        mapping.injectionwell_params_from_gemini(
            mapping.from_property(OLD_PROJECT / "injection_well_a06b.param")
        ),
    )
    stream = Stream(m_dot=Quantity(40, "kg/s"), T=Quantity(300, "K"), p=Quantity(5e6, "Pa"))
    chemistry = {"co2_fraction": 0.1}
    assert well.corrosion_profile(stream, chemistry, "DLM") == well.corrosion_profile(
        stream.with_(m_dot=-40), chemistry, "DLM"
    )


def _well():
    return si.set_params(
        InjectionWell(),
        "",
        mapping.injectionwell_params_from_gemini(
            mapping.from_property(OLD_PROJECT / "injection_well_a06b.param")
        ),
    )


def test_injection_traversal_matches_on_arrays():
    """The negative-flow traversal and its corrected bottom stream equal one call per row."""
    well = _well()

    def traversal(m_dot, T, p):
        stream = well._traversal_stream(Stream._si(m_dot=m_dot, T=T, p=p, fluid=DEFAULT_FLUID))
        result = well.traverse(stream, 0, well.pipe_path.total_length, "down")
        bottom = well.corrected(stream, result)
        return dict(
            p=bottom.p,
            T=bottom.T,
            friction_pressure_drop=result.friction_pressure_drop,
            gravity_pressure_drop=result.gravity_pressure_drop,
            first_pressure=result.section_pressure[0],
        )

    rows = [(40.0, 300.0, 5e6), (-40.0, 300.0, 5e6), (0.0, 300.0, 5e6), (3.0, 280.0, 1e5)]
    assert_function_matches(traversal, rows)


def test_injection_well_traces_with_its_section_profiles():
    """The per-section lists are vector outputs: the module traces and equals one call per row."""
    rows = [
        {
            "wellhead_in": Stream(
                m_dot=Quantity(40.0, "kg/s"), T=Quantity(353.15, "K"), p=Quantity(25e6, "Pa")
            )
        },
        {
            "wellhead_in": Stream(
                m_dot=Quantity(10.0, "kg/s"), T=Quantity(340.0, "K"), p=Quantity(20e6, "Pa")
            )
        },
        {
            "wellhead_in": Stream(
                m_dot=Quantity(25.0, "kg/s"), T=Quantity(300.0, "K"), p=Quantity(5e6, "Pa")
            )
        },
    ]
    assert_module_matches(_well(), rows)
    traced = run(
        _well(),
        {
            "wellhead_in": Stream(
                m_dot=Quantity(np.array([40.0, 10.0]), "kg/s"),
                T=Quantity(np.array([353.15, 340.0]), "K"),
                p=Quantity(np.array([25e6, 20e6]), "Pa"),
            )
        },
    )
    assert traced.breaks == [] and traced.outputs["section_pressure"].shape[0] == 2
