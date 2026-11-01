"""The closed lists of the case: equipment kinds and gas species."""

import gemini as gm
from gemini import units
from gemini.case._utils import kinds


def test_every_kind_has_a_known_quantity_and_a_basis():
    """The cost basis of each kind is a quantity the unit table knows."""
    for kind, (quantity, basis) in kinds.EQUIPMENT_KINDS.items():
        assert units.names(quantity) and basis, kind


def test_the_kinds_are_the_list_of_the_task():
    """Nineteen kinds, wells and pumps first."""
    assert len(kinds.EQUIPMENT_KINDS) == 19
    assert list(kinds.EQUIPMENT_KINDS)[:3] == ["drilling", "production_pump", "injection_pump"]
    assert kinds.EQUIPMENT_KINDS["chp"][1] == "per W of electric capacity"
    assert list(gm.case.Capex.model_fields) == list(kinds.EQUIPMENT_KINDS)


def test_the_gas_species_are_closed():
    """Four species."""
    assert kinds.GAS_SPECIES == ("CH4", "CO2", "N2", "H2S")
