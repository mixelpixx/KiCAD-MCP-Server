"""Construction smoke test for KiCADInterface.

Every tool PR touches two places that no per-module unit test exercises
together: the handler import block and the ``command_routes`` dict in
``kicad_interface.py``. A route entry that references a renamed or
un-imported function passes every module-level test but raises ``NameError``
the moment the server constructs the interface — i.e. the server crashes at
startup while CI stays green. PR #308 shipped exactly that
(``"add_library_symbol_property": add_schematic_symbol_property`` after a
module rename); this file makes the whole class unshippable.

Relies on conftest.py's pcbnew stub (``__file__`` and ``GetBuildVersion``
are accessed at kicad_interface module level).
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = pytest.mark.skipif(
    os.environ.get("KICAD_USE_REAL_PCBNEW") == "1",
    reason="construction smoke test targets the stubbed-pcbnew unit environment",
)


@pytest.fixture(scope="module")
def iface():
    with patch("kicad_interface.USE_IPC_BACKEND", False):
        from kicad_interface import KiCADInterface

        return KiCADInterface()


def test_interface_constructs_and_all_routes_are_callable(iface) -> None:
    routes = iface.command_routes
    assert len(routes) > 150, f"suspiciously few routes: {len(routes)}"
    not_callable = sorted(name for name, handler in routes.items() if not callable(handler))
    assert not not_callable, f"routes bound to non-callables: {not_callable}"


def test_every_schema_listed_tool_has_a_route(iface) -> None:
    """tools/list is built from TOOL_SCHEMAS; a schema without a route is a
    tool that advertises itself and then fails on call."""
    from schemas.tool_schemas import TOOL_SCHEMAS

    missing = sorted(set(TOOL_SCHEMAS) - set(iface.command_routes))
    assert not missing, f"schema-listed tools with no command route: {missing}"


def test_recently_added_tools_are_routed(iface) -> None:
    # Sentinels from the last few merges — the exact entries a bad rebase or
    # rename is most likely to drop.
    for tool in (
        "replace_instance_lib_ids",
        "update_symbol_from_library",
        "add_library_symbol_property",
        "add_symbol_property",
        "save_project",
        "close_project",
        "export_dsn",
        "import_ses",
    ):
        assert tool in iface.command_routes, f"missing route: {tool}"
