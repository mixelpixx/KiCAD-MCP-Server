"""Protocol tests for the pure-Python MCP server.

Everything runs against the SDK v2 in-memory Client — no transport, no
subprocess, no KiCAD required. Tools that need pcbnew or a running KiCAD must
fail *structurally* (an error payload), never crash the server.
"""

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

from mcp import Client  # noqa: E402

from kicad_mcp import registry  # noqa: E402
from kicad_mcp.prompts import prompt_count  # noqa: E402
from kicad_mcp.server import build_server  # noqa: E402

BASELINE_PATH = Path(__file__).parent / "fixtures" / "tools_baseline.json"
BASELINE = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
BASELINE_BY_NAME = {t["name"]: t for t in BASELINE}


@pytest.fixture(scope="module")
def server():
    return build_server()


# ---------------------------------------------------------------------------
# Parity with the TypeScript layer (the registry-is-truth invariant)
# ---------------------------------------------------------------------------


def test_registry_count_matches_baseline():
    assert registry.tool_count() == len(BASELINE)


@pytest.mark.anyio
async def test_tools_list_matches_baseline_exactly(server):
    async with Client(server) as client:
        result = await client.list_tools()
    names = sorted(t.name for t in result.tools)
    baseline_names = sorted(BASELINE_BY_NAME)
    assert names == baseline_names


@pytest.mark.anyio
async def test_required_params_match_baseline(server):
    async with Client(server) as client:
        result = await client.list_tools()
    mismatches = []
    for tool in result.tools:
        expected = set(BASELINE_BY_NAME[tool.name]["inputSchema"].get("required", []))
        actual = set(tool.input_schema.get("required") or [])
        if expected != actual:
            mismatches.append((tool.name, sorted(expected), sorted(actual)))
    assert not mismatches, f"required-set drift: {mismatches}"


@pytest.mark.anyio
async def test_property_names_match_baseline(server):
    async with Client(server) as client:
        result = await client.list_tools()
    mismatches = []
    for tool in result.tools:
        expected = set(BASELINE_BY_NAME[tool.name]["inputSchema"].get("properties") or {})
        actual = set(tool.input_schema.get("properties") or {})
        if expected != actual:
            mismatches.append((tool.name, sorted(expected ^ actual)))
    assert not mismatches, f"property drift: {mismatches}"


# ---------------------------------------------------------------------------
# Tool calls through the full stack (SDK -> toolset -> dispatch -> commands)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_file_based_tool_happy_path(server, tmp_path):
    """create_schematic writes a .kicad_sch with no KiCAD install at all."""
    async with Client(server) as client:
        result = await client.call_tool(
            "create_schematic",
            {"name": "testproj", "path": str(tmp_path)},
        )
    assert not result.is_error
    payload = result.structured_content
    assert payload.get("success") is True, payload
    created = list(tmp_path.rglob("*.kicad_sch"))
    assert created, "no .kicad_sch written"


@pytest.mark.anyio
async def test_swig_tool_without_pcbnew_fails_structurally(server, tmp_path):
    """Without pcbnew, SWIG tools return an error payload; the server survives."""
    pytest.importorskip("kicad_mcp.dispatch")
    from kicad_mcp import dispatch

    if not dispatch.PCBNEW_IMPORT_ERROR:
        pytest.skip("pcbnew importable here; the error path can't be exercised")

    async with Client(server) as client:
        result = await client.call_tool(
            "create_project",
            {"path": str(tmp_path), "name": "boardproj"},
        )
        # Structured failure, not a protocol error, and the session still works:
        payload = result.structured_content
        assert result.is_error or payload.get("success") is False
        again = await client.list_tools()
        assert len(again.tools) == len(BASELINE)


@pytest.mark.anyio
async def test_invalid_arguments_rejected_before_handler(server):
    async with Client(server) as client:
        result = await client.call_tool("create_schematic", {"projectName": 42})
    assert result.is_error


@pytest.mark.anyio
async def test_unknown_command_route_is_structured(server):
    """add_zone is registered (TS parity) but its route never existed;
    calling it must produce a structured failure, not a crash."""
    async with Client(server) as client:
        result = await client.call_tool("add_zone", {"layer": "F.Cu"})
        assert result.is_error or result.structured_content.get("success") is False
        still = await client.list_tools()
        assert len(still.tools) == len(BASELINE)


# ---------------------------------------------------------------------------
# Router meta-tools
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_router_list_and_search(server):
    async with Client(server) as client:
        cats = await client.call_tool("list_tool_categories", {})
        assert cats.structured_content["total_tools"] == len(BASELINE)

        bad = await client.call_tool("get_category_tools", {"category": "nope"})
        assert "available_categories" in bad.structured_content

        hits = await client.call_tool("search_tools", {"query": "gerber"})
        names = [m["name"] for m in hits.structured_content["matches"]]
        assert "export_gerber" in names


# ---------------------------------------------------------------------------
# Resources and prompts
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_resources_registered(server):
    async with Client(server) as client:
        result = await client.list_resources()
    assert len(result.resources) == 8


@pytest.mark.anyio
async def test_resource_read_without_project(server):
    async with Client(server) as client:
        result = await client.read_resource("kicad://project/current/info")
    assert result.contents


@pytest.mark.anyio
async def test_prompts_registered(server):
    async with Client(server) as client:
        result = await client.list_prompts()
    assert len(result.prompts) == prompt_count() == 18


@pytest.mark.anyio
async def test_prompt_get_interpolates(server):
    async with Client(server) as client:
        result = await client.get_prompt("routing_strategy", {"board_info": "4-layer, 100x80mm"})
    text = result.messages[0].content.text
    assert "4-layer, 100x80mm" in text
    assert "{{" not in text
