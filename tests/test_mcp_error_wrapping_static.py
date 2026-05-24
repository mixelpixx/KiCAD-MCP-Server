"""
Regression tests for MCP error wrapping in TypeScript tool adapters.

KiCad backend commands may report domain failures as JSON payloads such as
{"success": false, "message": "No board is loaded"}. The MCP tool result must
also be marked with isError so clients do not treat the failed command as OK.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
TOOLS_DIR = ROOT / "src" / "tools"
DESIGN_RULES_TS = TOOLS_DIR / "design-rules.ts"
TOOL_RESPONSE_TS = TOOLS_DIR / "tool-response.ts"


@pytest.mark.unit
class TestMcpErrorWrapping:
    def test_helper_marks_only_explicit_failure_payloads_as_mcp_errors(self):
        """A KiCad success:false payload must become an MCP isError result."""
        helper = TOOL_RESPONSE_TS.read_text(encoding="utf-8")

        assert "export function formatKicadResult" in helper
        assert "success === false" in helper
        assert "isError: true" in helper

    def test_design_rule_tools_use_shared_error_wrapper(self):
        """DRC/design-rule wrappers must not return success:false as a plain OK result."""
        source = DESIGN_RULES_TS.read_text(encoding="utf-8")

        assert 'import { formatKicadResult } from "./tool-response.js";' in source

        for command in (
            "set_design_rules",
            "get_design_rules",
            "run_drc",
            "add_net_class",
            "assign_net_to_class",
            "set_layer_constraints",
            "check_clearance",
            "get_drc_violations",
        ):
            marker = f'callKicadScript("{command}"'
            command_index = source.find(marker)
            assert command_index != -1, f"{command} wrapper not found"

            next_tool_index = source.find("server.tool(", command_index + len(marker))
            wrapper_body = source[command_index : next_tool_index if next_tool_index != -1 else None]
            assert "return formatKicadResult(result);" in wrapper_body
