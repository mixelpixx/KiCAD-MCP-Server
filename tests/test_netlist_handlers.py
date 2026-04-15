"""
Tests for export_netlist and generate_netlist handlers.

Covers:
  - Parameter validation (unit)
  - kicad-cli invocation and response parsing (unit, subprocess mocked)
  - XML → structured JSON conversion for generate_netlist (unit)
"""

import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))


# ---------------------------------------------------------------------------
# Shared fixture: KiCADInterface instance (no __init__, avoids pcbnew/IPC)
# ---------------------------------------------------------------------------


def _make_iface() -> Any:
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

        iface = KiCADInterface.__new__(KiCADInterface)
    return iface


@pytest.fixture()
def iface():
    return _make_iface()


# ---------------------------------------------------------------------------
# Sample KiCad XML netlist (minimal but structurally valid)
# ---------------------------------------------------------------------------

_KICAD_NETLIST_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <export version="E">
      <components>
        <comp ref="R1">
          <value>10k</value>
          <footprint>Resistor_SMD:R_0402</footprint>
        </comp>
        <comp ref="C1">
          <value>100n</value>
          <footprint>Capacitor_SMD:C_0402</footprint>
        </comp>
      </components>
      <nets>
        <net code="1" name="VCC">
          <node ref="R1" pin="1"/>
          <node ref="C1" pin="+"/>
        </net>
        <net code="2" name="GND">
          <node ref="R1" pin="2"/>
          <node ref="C1" pin="-"/>
        </net>
      </nets>
    </export>
""")


# ===========================================================================
# Dispatch: both commands wired into command_routes
# ===========================================================================


@pytest.mark.unit
class TestNetlistDispatch:
    def _make_full_iface(self) -> Any:
        with patch("kicad_interface.USE_IPC_BACKEND", False):
            from kicad_interface import KiCADInterface

            obj = KiCADInterface.__new__(KiCADInterface)
            obj.board = None
            obj.project_filename = None
            obj.use_ipc = False
            obj.ipc_backend = MagicMock()
            obj.ipc_board_api = None
            obj.footprint_library = MagicMock()
            obj.project_commands = MagicMock()
            obj.board_commands = MagicMock()
            obj.component_commands = MagicMock()
            obj.routing_commands = MagicMock()
            KiCADInterface.__init__(obj)
        return obj

    def test_export_netlist_in_routes(self):
        obj = self._make_full_iface()
        assert "export_netlist" in obj.command_routes
        assert callable(obj.command_routes["export_netlist"])

    def test_generate_netlist_in_routes(self):
        obj = self._make_full_iface()
        assert "generate_netlist" in obj.command_routes
        assert callable(obj.command_routes["generate_netlist"])


# ===========================================================================
# export_netlist
# ===========================================================================


@pytest.mark.unit
class TestExportNetlistValidation:
    def test_missing_schematic_path(self, iface, tmp_path):
        result = iface._handle_export_netlist({"outputPath": str(tmp_path / "out.xml")})
        assert result["success"] is False
        assert "schematicPath" in result["message"]

    def test_missing_output_path(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)")
        result = iface._handle_export_netlist({"schematicPath": str(sch)})
        assert result["success"] is False
        assert "outputPath" in result["message"]

    def test_schematic_not_found(self, iface, tmp_path):
        result = iface._handle_export_netlist(
            {
                "schematicPath": "/nonexistent/file.kicad_sch",
                "outputPath": str(tmp_path / "out.xml"),
            }
        )
        assert result["success"] is False
        assert "not found" in result["message"].lower()

    def test_kicad_cli_not_found(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)")
        with patch(
            "kicad_interface.KiCADInterface._find_kicad_cli_static", staticmethod(lambda: None)
        ):
            result = iface._handle_export_netlist(
                {"schematicPath": str(sch), "outputPath": str(tmp_path / "out.xml")}
            )
        assert result["success"] is False
        assert "kicad-cli" in result["message"]


@pytest.mark.unit
class TestExportNetlistCliInvocation:
    def _run_with_mock_cli(self, iface, tmp_path, fmt_param, expected_cli_fmt):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)")
        out = tmp_path / "out.net"
        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return MagicMock(returncode=0, stderr="")

        with (
            patch("subprocess.run", side_effect=fake_run),
            patch(
                "kicad_interface.KiCADInterface._find_kicad_cli_static",
                staticmethod(lambda: "/usr/bin/kicad-cli"),
            ),
        ):
            result = iface._handle_export_netlist(
                {"schematicPath": str(sch), "outputPath": str(out), "format": fmt_param}
            )

        assert result["success"] is True, result
        assert expected_cli_fmt in captured["cmd"]
        assert str(sch) in captured["cmd"]
        assert str(out) in captured["cmd"]

    def test_format_spice(self, iface, tmp_path):
        self._run_with_mock_cli(iface, tmp_path, "Spice", "spice")

    def test_format_kicad(self, iface, tmp_path):
        self._run_with_mock_cli(iface, tmp_path, "KiCad", "kicadxml")

    def test_format_cadstar(self, iface, tmp_path):
        self._run_with_mock_cli(iface, tmp_path, "Cadstar", "cadstar")

    def test_format_orcadpcb2(self, iface, tmp_path):
        self._run_with_mock_cli(iface, tmp_path, "OrcadPCB2", "orcadpcb2")

    def test_response_contains_output_path(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)")
        out = tmp_path / "out.net"

        with (
            patch("subprocess.run", return_value=MagicMock(returncode=0, stderr="")),
            patch(
                "kicad_interface.KiCADInterface._find_kicad_cli_static",
                staticmethod(lambda: "/usr/bin/kicad-cli"),
            ),
        ):
            result = iface._handle_export_netlist(
                {"schematicPath": str(sch), "outputPath": str(out), "format": "Spice"}
            )

        assert result["success"] is True
        assert result["outputPath"] == str(out)
        assert result["format"] == "Spice"

    def test_cli_failure_propagated(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)")

        with (
            patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="bad input")),
            patch(
                "kicad_interface.KiCADInterface._find_kicad_cli_static",
                staticmethod(lambda: "/usr/bin/kicad-cli"),
            ),
        ):
            result = iface._handle_export_netlist(
                {"schematicPath": str(sch), "outputPath": str(tmp_path / "out.net")}
            )

        assert result["success"] is False
        assert "bad input" in result["message"]

    def test_cli_timeout_propagated(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)")

        with (
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired("kicad-cli", 60)),
            patch(
                "kicad_interface.KiCADInterface._find_kicad_cli_static",
                staticmethod(lambda: "/usr/bin/kicad-cli"),
            ),
        ):
            result = iface._handle_export_netlist(
                {"schematicPath": str(sch), "outputPath": str(tmp_path / "out.net")}
            )

        assert result["success"] is False
        assert "timed out" in result["message"].lower()


# ===========================================================================
# generate_netlist
# ===========================================================================


@pytest.mark.unit
class TestGenerateNetlistValidation:
    def test_missing_schematic_path(self, iface):
        result = iface._handle_generate_netlist({})
        assert result["success"] is False
        assert "required" in result["message"].lower()

    def test_schematic_not_found(self, iface):
        result = iface._handle_generate_netlist({"schematicPath": "/nonexistent/file.kicad_sch"})
        assert result["success"] is False
        assert "not found" in result["message"].lower()

    def test_kicad_cli_not_found(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)")
        with patch(
            "kicad_interface.KiCADInterface._find_kicad_cli_static", staticmethod(lambda: None)
        ):
            result = iface._handle_generate_netlist({"schematicPath": str(sch)})
        assert result["success"] is False
        assert "kicad-cli" in result["message"]


@pytest.mark.unit
class TestGenerateNetlistXmlParsing:
    """Verify the XML → JSON conversion is correct."""

    def _call_with_xml(self, iface, tmp_path, xml_content):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)")

        def fake_run(cmd, **kwargs):
            # Write the XML to the --output path in the command
            out_idx = cmd.index("--output") + 1
            Path(cmd[out_idx]).write_text(xml_content)
            return MagicMock(returncode=0, stderr="")

        with (
            patch("subprocess.run", side_effect=fake_run),
            patch(
                "kicad_interface.KiCADInterface._find_kicad_cli_static",
                staticmethod(lambda: "/usr/bin/kicad-cli"),
            ),
        ):
            return iface._handle_generate_netlist({"schematicPath": str(sch)})

    def test_success_flag(self, iface, tmp_path):
        result = self._call_with_xml(iface, tmp_path, _KICAD_NETLIST_XML)
        assert result["success"] is True

    def test_components_count(self, iface, tmp_path):
        result = self._call_with_xml(iface, tmp_path, _KICAD_NETLIST_XML)
        assert len(result["netlist"]["components"]) == 2

    def test_component_refs(self, iface, tmp_path):
        result = self._call_with_xml(iface, tmp_path, _KICAD_NETLIST_XML)
        refs = {c["reference"] for c in result["netlist"]["components"]}
        assert refs == {"R1", "C1"}

    def test_component_fields(self, iface, tmp_path):
        result = self._call_with_xml(iface, tmp_path, _KICAD_NETLIST_XML)
        r1 = next(c for c in result["netlist"]["components"] if c["reference"] == "R1")
        assert r1["value"] == "10k"
        assert r1["footprint"] == "Resistor_SMD:R_0402"

    def test_nets_count(self, iface, tmp_path):
        result = self._call_with_xml(iface, tmp_path, _KICAD_NETLIST_XML)
        assert len(result["netlist"]["nets"]) == 2

    def test_net_names(self, iface, tmp_path):
        result = self._call_with_xml(iface, tmp_path, _KICAD_NETLIST_XML)
        names = {n["name"] for n in result["netlist"]["nets"]}
        assert names == {"VCC", "GND"}

    def test_net_connections(self, iface, tmp_path):
        result = self._call_with_xml(iface, tmp_path, _KICAD_NETLIST_XML)
        vcc = next(n for n in result["netlist"]["nets"] if n["name"] == "VCC")
        assert len(vcc["connections"]) == 2
        comps = {c["component"] for c in vcc["connections"]}
        assert comps == {"R1", "C1"}

    def test_cli_failure_propagated(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)")

        with (
            patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="parse error")),
            patch(
                "kicad_interface.KiCADInterface._find_kicad_cli_static",
                staticmethod(lambda: "/usr/bin/kicad-cli"),
            ),
        ):
            result = iface._handle_generate_netlist({"schematicPath": str(sch)})

        assert result["success"] is False
        assert "parse error" in result["message"]

    def test_cli_timeout_propagated(self, iface, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("(kicad_sch)")

        with (
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired("kicad-cli", 60)),
            patch(
                "kicad_interface.KiCADInterface._find_kicad_cli_static",
                staticmethod(lambda: "/usr/bin/kicad-cli"),
            ),
        ):
            result = iface._handle_generate_netlist({"schematicPath": str(sch)})

        assert result["success"] is False
        assert "timed out" in result["message"].lower()

    def test_empty_schematic(self, iface, tmp_path):
        empty_xml = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <export version="E">
              <components/>
              <nets/>
            </export>
        """)
        result = self._call_with_xml(iface, tmp_path, empty_xml)
        assert result["success"] is True
        assert result["netlist"]["components"] == []
        assert result["netlist"]["nets"] == []
