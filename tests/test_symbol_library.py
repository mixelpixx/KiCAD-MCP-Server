"""
Regression tests for symbol library parsing.

Covers:
- The 5000-char heuristic bug where PJFET properties bled into the OPAMP block.
- The sim_pins field exposed from Sim.Pins properties.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from commands.library_symbol import SymbolLibraryCommands, SymbolLibraryManager

FIXTURE = Path(__file__).parent / "fixtures" / "Simulation_SPICE_minimal.kicad_sym"
SPICE_LIB = Path("/usr/share/kicad/symbols/Simulation_SPICE.kicad_sym")


def _manager_for_fixture() -> SymbolLibraryManager:
    manager = SymbolLibraryManager.__new__(SymbolLibraryManager)
    manager.project_path = None
    manager.libraries = {"Simulation_SPICE": str(FIXTURE)}
    manager.symbol_cache = {}
    return manager


@pytest.mark.unit
class TestSymbolLibraryManagerParsing:
    """Unit tests using the minimal fixture file (no disk I/O to system libs)."""

    def test_both_symbols_present(self):
        manager = _manager_for_fixture()
        symbols = manager.list_symbols("Simulation_SPICE")
        names = [s.name for s in symbols]
        assert "OPAMP" in names
        assert "PJFET" in names
        assert len(symbols) == 2

    def test_opamp_description_is_not_pjfet(self):
        manager = _manager_for_fixture()
        symbols = manager.list_symbols("Simulation_SPICE")
        opamp = next(s for s in symbols if s.name == "OPAMP")
        assert "JFET" not in opamp.description

    def test_opamp_description_correct(self):
        manager = _manager_for_fixture()
        symbols = manager.list_symbols("Simulation_SPICE")
        opamp = next(s for s in symbols if s.name == "OPAMP")
        assert opamp.description == "Operational amplifier, single"

    def test_opamp_value_correct(self):
        manager = _manager_for_fixture()
        symbols = manager.list_symbols("Simulation_SPICE")
        opamp = next(s for s in symbols if s.name == "OPAMP")
        assert opamp.value == "${SIM.PARAMS}"

    def test_opamp_sim_pins_exposed(self):
        manager = _manager_for_fixture()
        symbols = manager.list_symbols("Simulation_SPICE")
        opamp = next(s for s in symbols if s.name == "OPAMP")
        assert opamp.sim_pins == "1=in+ 2=in- 3=vcc 4=vee 5=out"

    def test_pjfet_description_correct(self):
        manager = _manager_for_fixture()
        symbols = manager.list_symbols("Simulation_SPICE")
        pjfet = next(s for s in symbols if s.name == "PJFET")
        assert pjfet.description == "P-JFET transistor, for simulation only"

    def test_pjfet_value_correct(self):
        manager = _manager_for_fixture()
        symbols = manager.list_symbols("Simulation_SPICE")
        pjfet = next(s for s in symbols if s.name == "PJFET")
        assert pjfet.value == "PJFET"

    def test_pjfet_sim_pins_exposed(self):
        manager = _manager_for_fixture()
        symbols = manager.list_symbols("Simulation_SPICE")
        pjfet = next(s for s in symbols if s.name == "PJFET")
        assert pjfet.sim_pins == "1=D 2=G 3=S"


@pytest.mark.integration
class TestGetSymbolInfoHandler:
    """Integration tests against the real system Simulation_SPICE library."""

    def test_opamp_via_commands_handler(self):
        if not SPICE_LIB.exists():
            pytest.skip(f"System library not found: {SPICE_LIB}")
        manager = SymbolLibraryManager.__new__(SymbolLibraryManager)
        manager.project_path = None
        manager.libraries = {"Simulation_SPICE": str(SPICE_LIB)}
        manager.symbol_cache = {}
        commands = SymbolLibraryCommands(library_manager=manager)
        result = commands.get_symbol_info({"symbol": "Simulation_SPICE:OPAMP"})
        assert result["success"] is True
        info = result["symbol_info"]
        assert info["description"] == "Operational amplifier, single"
        assert "JFET" not in info["description"]
        assert info["value"] == "${SIM.PARAMS}"
        assert info["sim_pins"] == "1=in+ 2=in- 3=vcc 4=vee 5=out"

    def test_pjfet_via_commands_handler(self):
        if not SPICE_LIB.exists():
            pytest.skip(f"System library not found: {SPICE_LIB}")
        manager = SymbolLibraryManager.__new__(SymbolLibraryManager)
        manager.project_path = None
        manager.libraries = {"Simulation_SPICE": str(SPICE_LIB)}
        manager.symbol_cache = {}
        commands = SymbolLibraryCommands(library_manager=manager)
        result = commands.get_symbol_info({"symbol": "Simulation_SPICE:PJFET"})
        assert result["success"] is True
        info = result["symbol_info"]
        assert info["description"] == "P-JFET transistor, for simulation only"
        assert info["value"] == "PJFET"
