"""
Tests for .kicad_pro net_settings preservation across open/save.

pcbnew reuses a stale in-memory project model when a project is re-opened
in the long-lived backend process; the next SaveBoard/BOARD.Save then
serializes that stale model over the hand-edited .kicad_pro, reverting
custom net classes and netclass_patterns to Default-only. The
utils.project_settings_guard helpers snapshot/merge/restore around every
backend-initiated save so user settings survive.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from utils.project_settings_guard import (  # noqa: E402
    merge_preserved_keys,
    preserve_project_settings,
    restore_project_file_if_changed,
    snapshot_project_file,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CUSTOM_NET_SETTINGS = {
    "classes": [
        {"name": "Default", "clearance": 0.2},
        {"name": "CAN_DIFF", "clearance": 0.2, "track_width": 0.3},
    ],
    "meta": {"version": 4},
    "netclass_patterns": [{"netclass": "CAN_DIFF", "pattern": "/CAN_*"}],
}

_DEFAULT_ONLY_NET_SETTINGS = {
    "classes": [{"name": "Default", "clearance": 0.2}],
    "meta": {"version": 4},
    "netclass_patterns": [],
}


def _make_project(tmp_path, net_settings=None, extra=None, write_board=True):
    board_path = tmp_path / "t.kicad_pcb"
    if write_board:
        board_path.write_text("(kicad_pcb)")
    pro = {
        "board": {"design_settings": {"defaults": {"track_width": 0.25}}},
        "net_settings": net_settings or _CUSTOM_NET_SETTINGS,
        "meta": {"filename": "t.kicad_pro", "version": 3},
    }
    if extra:
        pro.update(extra)
    pro_path = tmp_path / "t.kicad_pro"
    pro_path.write_text(json.dumps(pro, indent=2))
    return str(board_path), str(pro_path)


def _clobber_pro(pro_path: str) -> None:
    """Simulate a destructive pcbnew save: net_settings reverted to
    Default-only, an unknown key dropped, design_settings updated."""
    with open(pro_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data["net_settings"] = json.loads(json.dumps(_DEFAULT_ONLY_NET_SETTINGS))
    data.pop("custom_unknown_key", None)
    data.setdefault("board", {}).setdefault("design_settings", {}).setdefault(
        "defaults", {}
    )["track_width"] = 0.42
    with open(pro_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


# ---------------------------------------------------------------------------
# merge_preserved_keys (pure)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMergePreservedKeys:
    def test_net_settings_restored(self):
        before = {"net_settings": _CUSTOM_NET_SETTINGS, "a": 1}
        after = {"net_settings": _DEFAULT_ONLY_NET_SETTINGS, "a": 1}
        merged, changed = merge_preserved_keys(before, after)
        assert changed is True
        assert merged["net_settings"] == _CUSTOM_NET_SETTINGS

    def test_dropped_unknown_key_restored(self):
        before = {"net_settings": {}, "custom_unknown_key": {"x": 1}}
        after = {"net_settings": {}}
        merged, changed = merge_preserved_keys(before, after)
        assert changed is True
        assert merged["custom_unknown_key"] == {"x": 1}

    def test_legitimate_after_values_kept(self):
        before = {
            "net_settings": _CUSTOM_NET_SETTINGS,
            "board": {"design_settings": {"defaults": {"track_width": 0.25}}},
        }
        after = {
            "net_settings": _CUSTOM_NET_SETTINGS,
            "board": {"design_settings": {"defaults": {"track_width": 0.42}}},
        }
        merged, changed = merge_preserved_keys(before, after)
        assert changed is False
        assert merged["board"]["design_settings"]["defaults"]["track_width"] == 0.42

    def test_no_change_when_nothing_lost(self):
        before = {"net_settings": _CUSTOM_NET_SETTINGS}
        after = {"net_settings": json.loads(json.dumps(_CUSTOM_NET_SETTINGS))}
        merged, changed = merge_preserved_keys(before, after)
        assert changed is False
        assert merged == after

    def test_inputs_not_mutated(self):
        before = {"net_settings": _CUSTOM_NET_SETTINGS, "gone": 1}
        after = {"net_settings": _DEFAULT_ONLY_NET_SETTINGS}
        after_copy = json.loads(json.dumps(after))
        merge_preserved_keys(before, after)
        assert after == after_copy


# ---------------------------------------------------------------------------
# preserve_project_settings context manager
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPreserveProjectSettings:
    def test_clobbering_save_is_merged_back(self, tmp_path):
        board_path, pro_path = _make_project(
            tmp_path, extra={"custom_unknown_key": {"keep": True}}
        )
        with preserve_project_settings(board_path):
            _clobber_pro(pro_path)

        data = json.loads(Path(pro_path).read_text())
        names = [c["name"] for c in data["net_settings"]["classes"]]
        assert "CAN_DIFF" in names
        assert data["net_settings"]["netclass_patterns"] == [
            {"netclass": "CAN_DIFF", "pattern": "/CAN_*"}
        ]
        assert data["custom_unknown_key"] == {"keep": True}
        # Legit design_settings change made by the save is kept
        assert data["board"]["design_settings"]["defaults"]["track_width"] == 0.42

    def test_noop_when_nothing_lost(self, tmp_path):
        board_path, pro_path = _make_project(tmp_path)
        original = Path(pro_path).read_text()
        with preserve_project_settings(board_path):
            pass
        assert Path(pro_path).read_text() == original

    def test_noop_without_project_file(self, tmp_path):
        board_path = tmp_path / "lonely.kicad_pcb"
        board_path.write_text("(kicad_pcb)")
        with preserve_project_settings(str(board_path)):
            pass  # must not raise or create a .kicad_pro
        assert not (tmp_path / "lonely.kicad_pro").exists()

    def test_never_raises_on_unparseable_project(self, tmp_path):
        board_path, pro_path = _make_project(tmp_path)
        Path(pro_path).write_text("{not json")
        with preserve_project_settings(board_path):
            pass  # snapshot unparseable -> guard is a no-op

    def test_exception_in_body_still_merges(self, tmp_path):
        board_path, pro_path = _make_project(tmp_path)
        with pytest.raises(RuntimeError):
            with preserve_project_settings(board_path):
                _clobber_pro(pro_path)
                raise RuntimeError("save blew up")
        data = json.loads(Path(pro_path).read_text())
        names = [c["name"] for c in data["net_settings"]["classes"]]
        assert "CAN_DIFF" in names


# ---------------------------------------------------------------------------
# open_project verbatim restore (mocked pcbnew)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOpenProjectRestore:
    def _commands(self) -> Any:
        from commands.project import ProjectCommands

        return ProjectCommands()

    def test_open_project_restores_clobbered_pro(self, tmp_path):
        board_path, pro_path = _make_project(tmp_path)
        original = Path(pro_path).read_text()
        commands = self._commands()

        def destructive_load(path):
            # Simulate a KiCad build whose LoadBoard rewrites .kicad_pro
            _clobber_pro(pro_path)
            return object()

        with patch("commands.project.pcbnew.LoadBoard", side_effect=destructive_load):
            result = commands.open_project({"filename": pro_path})

        assert result["success"], result
        assert Path(pro_path).read_text() == original

    def test_open_project_untouched_pro_not_rewritten(self, tmp_path):
        board_path, pro_path = _make_project(tmp_path)
        commands = self._commands()
        mtime = os.path.getmtime(pro_path)
        with patch("commands.project.pcbnew.LoadBoard", return_value=object()):
            result = commands.open_project({"filename": pro_path})
        assert result["success"], result
        assert os.path.getmtime(pro_path) == mtime

    def test_snapshot_restore_helpers(self, tmp_path):
        board_path, pro_path = _make_project(tmp_path)
        snap = snapshot_project_file(board_path)
        assert snap is not None
        assert restore_project_file_if_changed(board_path, snap) is False
        Path(pro_path).write_text("{}")
        assert restore_project_file_if_changed(board_path, snap) is True
        assert Path(pro_path).read_bytes() == snap
        assert snapshot_project_file(str(tmp_path / "none.kicad_pcb")) is None


# ---------------------------------------------------------------------------
# Real-SWIG round trip (gated)
# ---------------------------------------------------------------------------


@pytest.mark.real_pcbnew
class TestRealPcbnewRoundTrip:
    @pytest.fixture(autouse=True)
    def _require_real_pcbnew(self):
        if os.environ.get("KICAD_USE_REAL_PCBNEW") != "1":
            pytest.skip("set KICAD_USE_REAL_PCBNEW=1 to run against real pcbnew")

    def test_stale_model_sequence_preserves_net_settings(self, tmp_path):
        import pcbnew

        board_path = str(tmp_path / "t.kicad_pcb")
        board = pcbnew.BOARD()
        pcbnew.SaveBoard(board_path, board)

        _, pro_path = _make_project(tmp_path, write_board=False)

        # Replay the confirmed clobber sequence: load, hand-edit .kicad_pro,
        # load again (stale in-memory project model), save via the guard.
        # Keep the first board referenced: letting SWIG garbage-collect it
        # mid-sequence can crash the interpreter.
        board1 = pcbnew.LoadBoard(board_path)  # noqa: F841
        data = json.loads(Path(pro_path).read_text())
        data["net_settings"] = json.loads(json.dumps(_CUSTOM_NET_SETTINGS))
        Path(pro_path).write_text(json.dumps(data, indent=2))

        board2 = pcbnew.LoadBoard(board_path)
        with preserve_project_settings(board_path):
            pcbnew.SaveBoard(board_path, board2)

        final = json.loads(Path(pro_path).read_text())
        names = [c["name"] for c in final["net_settings"]["classes"]]
        assert "CAN_DIFF" in names
        assert {"netclass": "CAN_DIFF", "pattern": "/CAN_*"} in final[
            "net_settings"
        ]["netclass_patterns"]
