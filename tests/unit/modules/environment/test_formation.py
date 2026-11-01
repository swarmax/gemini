"""The rock around the wells of a doublet."""

import gemini as gm
from gemini.modules import Formation
from tests.fixtures.equivalence import assert_module_matches


def test_the_rock_receives_the_heat_of_the_wells():
    """The port holds what arrives."""
    assert Formation()(heat_in=[1e3, 2e3]).inlets.heat_in == [1e3, 2e3]


def test_a_doublet_passes_it_the_values_of_its_design():
    """The gradient and the surface temperature are those the wells get."""
    doublet = gm.plants.Doublet().set_params(
        "",
        {
            "depth": {"value": 2500, "unit": "m"},
            "gradient": {"value": 30, "unit": "K/km"},
            "surface_temperature": {"value": 12, "unit": "degC"},
        },
    )
    assert doublet.formation.geothermal_gradient == 0.03
    assert doublet.formation.surface_temperature == 285.15


def test_traced_call_matches_one_call_per_row():
    """A leaf with nothing to compute traces."""
    assert_module_matches(Formation(), [{}, {}])
