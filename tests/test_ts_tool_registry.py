"""
Regression test: no MCP tool name is registered more than once across all
TypeScript tool files in src/tools/.

This caught a real bug where move_schematic_component was registered twice
(once in the original code and once in the PR adding wire-preservation),
causing the server to fail on startup with:
  Error: Tool move_schematic_component is already registered
"""

import re
from collections import Counter
from pathlib import Path

import pytest

SRC_TOOLS_DIR = Path(__file__).parent.parent / "src" / "tools"

# Pattern matches the tool-name argument to server.tool(
#   server.tool(
#     "some_tool_name",
_SERVER_TOOL_RE = re.compile(r'server\.tool\(\s*["\']([a-zA-Z0-9_]+)["\']')


@pytest.mark.unit
class TestTsToolRegistry:
    def _collect_registrations(self):
        """Return list of (tool_name, file, line_no) for every server.tool() call."""
        registrations = []
        for ts_file in sorted(SRC_TOOLS_DIR.glob("**/*.ts")):
            text = ts_file.read_text(encoding="utf-8")
            for m in _SERVER_TOOL_RE.finditer(text):
                line_no = text[: m.start()].count("\n") + 1
                registrations.append((m.group(1), ts_file.name, line_no))
        return registrations

    def test_no_duplicate_tool_names(self):
        """Every tool name must appear exactly once across all TS tool files."""
        registrations = self._collect_registrations()
        assert registrations, "No server.tool() calls found — check SRC_TOOLS_DIR path"

        counts = Counter(name for name, _, _ in registrations)
        duplicates = {name: count for name, count in counts.items() if count > 1}

        if duplicates:
            details = []
            for dup_name in sorted(duplicates):
                locations = [
                    f"  {fname}:{line}" for name, fname, line in registrations if name == dup_name
                ]
                details.append(f"{dup_name} ({duplicates[dup_name]}x):\n" + "\n".join(locations))
            pytest.fail(
                "Duplicate MCP tool registrations found — server will fail to start:\n\n"
                + "\n\n".join(details)
            )

    def test_tool_files_exist(self):
        """Sanity check: src/tools/ directory must be present and contain TS files."""
        assert SRC_TOOLS_DIR.is_dir(), f"src/tools/ not found at {SRC_TOOLS_DIR}"
        ts_files = list(SRC_TOOLS_DIR.glob("**/*.ts"))
        assert ts_files, "No .ts files found in src/tools/"
