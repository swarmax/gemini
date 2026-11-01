"""The JSON Schema of the plant spec."""

import json

import pytest

import gemini as gm


def test_the_schema_is_plain_json_listing_every_module_type_and_group():
    """Types are an enumeration of the registry and the two groups."""
    schema = gm.plants.schema()
    assert json.loads(json.dumps(schema)) == schema
    assert schema["$schema"].endswith("2020-12/schema")
    types = schema["$defs"]["module"]["properties"]["type"]["enum"]
    assert {"Filter", "Doublet", "ModuleDict", "ModuleList"} <= set(types)


def test_the_schema_has_the_two_forms_of_a_plant_dict():
    """A plant of a class names it; any other plant states its modules and connections."""
    of_class, with_structure = gm.plants.schema()["anyOf"]
    assert of_class["required"] == ["format", "type"]
    assert set(of_class["properties"]["type"]["enum"]) == set(gm.plants.names())
    assert with_structure["required"] == ["format", "name", "modules", "connections"]


def test_the_schema_accepts_only_the_keys_a_plant_dict_holds():
    """Every key a plant writes is declared, in both forms."""
    of_class, with_structure = gm.plants.schema()["anyOf"]
    plant = gm.plants.example("NodalDoublet")
    assert set(plant.to_dict()) <= set(of_class["properties"])
    assert set(plant.to_dict(structure=True)) <= set(with_structure["properties"])


def test_the_schema_lists_the_forms_of_an_output_and_nothing_removed():
    """Outputs are the three combinations."""
    _, with_structure = gm.plants.schema()["anyOf"]
    forms = with_structure["properties"]["outputs"]["additionalProperties"]["properties"]
    assert set(forms) == {"difference", "ratio", "sum"}


def test_the_inputs_schema_takes_a_number_or_a_quantity_and_refuses_a_unit_string():
    """``set_inputs`` refuses a unit string, so the schema does not offer one."""
    inputs = gm.plants.schema()["anyOf"][1]["properties"]["inputs"]
    assert [branch["type"] for branch in inputs["additionalProperties"]["anyOf"]] == [
        "number",
        "object",
    ]
    assert "unit string" not in inputs["description"]
    plant = gm.plants.example("NodalDoublet")
    with pytest.raises(gm.errors.ValidationError):
        plant.set_inputs({"reservoir.production_rate": "5 kg/s"})
