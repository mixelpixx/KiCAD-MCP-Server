"""JLCPCBPartsManager degrades gracefully when its database is unavailable.

Regression guard for #264: an unwritable data directory (or database file)
raised PermissionError during construction, which happened at server import
time -- one broken directory took down all 216 tools. The manager now
disables itself with a warning and every operation returns an empty result
instead of raising.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

pytestmark = pytest.mark.unit

from commands.jlcpcb_parts import JLCPCBPartsManager  # noqa: E402


def _disabled_manager():
    with patch("commands.jlcpcb_parts.PlatformHelper.get_data_dir") as get_dir:
        get_dir.return_value.mkdir.side_effect = PermissionError("denied")
        return JLCPCBPartsManager()


def test_unwritable_data_dir_disables_instead_of_raising():
    mgr = _disabled_manager()
    assert mgr.conn is None


def test_disabled_manager_operations_return_empty_results():
    mgr = _disabled_manager()
    assert mgr.search_parts(query="R0402") == []
    assert mgr.get_part_info("C12345") is None
    stats = mgr.get_database_stats()
    assert stats["total_parts"] == 0
    mgr.import_parts([])  # must not raise
    mgr.close()  # must not raise


def test_unopenable_database_file_disables_instead_of_raising(tmp_path):
    # Point db_path at a directory -- sqlite cannot open that as a database.
    mgr = JLCPCBPartsManager(db_path=str(tmp_path))
    assert mgr.conn is None
    assert mgr.search_parts(query="x") == []
