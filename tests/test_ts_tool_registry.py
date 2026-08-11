"""Static parity checks for TypeScript MCP tools and Python command routes."""

import ast
import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SRC_TOOLS_DIR = ROOT / "src" / "tools"
PYTHON_INTERFACE = ROOT / "python" / "kicad_interface.py"

_REGISTER_TOOL_RE = re.compile(
    r'registerKiCadTool\(\s*server,\s*["\'](?P<category>[a-z0-9_]+)["\']\s*,\s*'
    r'["\'](?P<name>[a-zA-Z0-9_]+)["\']'
)
_BACKEND_CALL_RE = re.compile(r'callKicadScript\(\s*["\']([a-zA-Z0-9_]+)["\']')


def _command_routes() -> set[str]:
    tree = ast.parse(PYTHON_INTERFACE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Attribute) and target.attr == "command_routes"
            for target in node.targets
        ):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        return {
            key.value
            for key in node.value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
    raise AssertionError("KiCADInterface.command_routes dictionary was not found")


@pytest.mark.unit
class TestTsToolRegistry:
    def _collect_registrations(self):
        registrations = []
        for ts_file in sorted(SRC_TOOLS_DIR.glob("*.ts")):
            text = ts_file.read_text(encoding="utf-8")
            for match in _REGISTER_TOOL_RE.finditer(text):
                line_no = text[: match.start()].count("\n") + 1
                registrations.append(
                    (match.group("name"), match.group("category"), ts_file.name, line_no)
                )
        return registrations

    def test_no_duplicate_tool_names(self):
        registrations = self._collect_registrations()
        assert registrations, "No registerKiCadTool() calls found"

        counts = Counter(name for name, _, _, _ in registrations)
        duplicates = {name: count for name, count in counts.items() if count > 1}
        assert not duplicates, f"Duplicate MCP tool registrations found: {duplicates}"

    def test_all_tool_modules_use_the_catalog_registration_wrapper(self):
        offenders = []
        for ts_file in sorted(SRC_TOOLS_DIR.glob("*.ts")):
            if ts_file.name == "tool-registration.ts":
                continue
            if "server.registerTool(" in ts_file.read_text(encoding="utf-8"):
                offenders.append(ts_file.name)
        assert offenders == []

    def test_every_typescript_backend_command_has_a_python_route(self):
        routes = _command_routes()
        calls: dict[str, list[str]] = {}
        for ts_file in sorted(SRC_TOOLS_DIR.glob("*.ts")):
            text = ts_file.read_text(encoding="utf-8")
            for command in _BACKEND_CALL_RE.findall(text):
                calls.setdefault(command, []).append(ts_file.name)

        missing = {command: files for command, files in calls.items() if command not in routes}
        assert missing == {}

    def test_unimplemented_phantom_tools_are_not_advertised(self):
        names = {name for name, _, _, _ in self._collect_registrations()}
        assert names.isdisjoint(
            {
                "add_component_annotation",
                "group_components",
                "replace_component",
            }
        )

    def test_supported_compatibility_aliases_remain_advertised(self):
        names = {name for name, _, _, _ in self._collect_registrations()}
        assert {
            "add_zone",
            "add_net_class",
            "assign_net_to_class",
            "check_clearance",
            "export_position_file",
            "export_vrml",
            "set_layer_constraints",
        } <= names

    def test_backend_state_tool_is_registered(self):
        names = {name for name, _, _, _ in self._collect_registrations()}
        assert "get_backend_state" in names
