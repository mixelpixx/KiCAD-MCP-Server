"""The Python-direct MCP catalog and the worker must agree on assembly variants."""

import pytest


@pytest.mark.parametrize(
    "name, required, optional",
    [
        ("list_variants", {"projectPath"}, set()),
        ("create_variant", {"projectPath", "name"}, {"description"}),
        ("get_component_variant", {"projectPath", "schematicPath", "reference", "variant"}, set()),
        (
            "set_component_variant",
            {"projectPath", "schematicPath", "reference", "variant"},
            {"dnp", "fields", "reset"},
        ),
        ("export_variant_bom", {"projectPath", "variant", "outputPath"}, {"excludeDnp"}),
    ],
)
def test_direct_catalog(name, required, optional):
    from schemas.tool_schemas import TOOL_SCHEMAS

    schema = TOOL_SCHEMAS[name]["inputSchema"]
    assert set(schema["required"]) == required
    assert set(schema["properties"]) == required | optional
    assert all(schema["properties"][key]["type"] == "string" for key in required)
    if "fields" in optional:
        assert set(schema["properties"]["fields"]["additionalProperties"]["type"]) == {
            "string",
            "null",
        }
