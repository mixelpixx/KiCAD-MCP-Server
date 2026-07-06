"""Preserve hand-edited ``.kicad_pro`` settings across backend board saves.

In the long-lived backend process, pcbnew reuses a stale in-memory project
model when a project is re-opened: ``pcbnew.LoadBoard`` does not re-read a
hand-edited ``.kicad_pro``, and the next ``pcbnew.SaveBoard`` /
``BOARD.Save()`` (default ``aSkipSettings=False`` — including the
post-mutation auto-save) serializes that stale model over the file,
reverting custom net classes and ``netclass_patterns`` to Default-only.

The backend never legitimately mutates ``net_settings`` through the pcbnew
model (``create_netclass`` persists via direct JSON read-modify-write), so
it is always safe to restore the on-disk ``net_settings`` — and any dropped
unknown top-level keys — after a save, while letting SaveBoard's legitimate
updates (e.g. ``board.design_settings``) flow through.

All helpers are best-effort and never raise: a guard failure must not fail
the board operation it wraps.
"""

import json
import logging
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("kicad_interface")


def _pro_path_for(board_path: str) -> Optional[str]:
    try:
        if not board_path:
            return None
        return str(Path(board_path).with_suffix(".kicad_pro"))
    except Exception:
        return None


def merge_preserved_keys(
    before: Dict[str, Any], after: Dict[str, Any]
) -> Tuple[Dict[str, Any], bool]:
    """Merge the pre-save project dict into the post-save one.

    Rules:
      * ``net_settings`` is restored wholesale from ``before`` (the backend
        never mutates it through the pcbnew model).
      * Top-level keys present in ``before`` but dropped by the save are
        re-added.
      * Every other value from ``after`` (e.g. ``board.design_settings``
        updated by set_design_rules) is kept.

    Returns ``(merged, changed)`` where ``changed`` is True when anything
    had to be restored. Pure function — inputs are not mutated.
    """
    merged = dict(after)
    changed = False

    if "net_settings" in before and merged.get("net_settings") != before["net_settings"]:
        merged["net_settings"] = before["net_settings"]
        changed = True

    for key, value in before.items():
        if key not in merged:
            merged[key] = value
            changed = True

    return merged, changed


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write_json_atomic(path: str, data: Dict[str, Any]) -> None:
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(
        dir=directory, prefix=".prosettings-", suffix=".kicad_pro"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise


@contextmanager
def preserve_project_settings(board_path: Optional[str]):
    """Guard a board save so it cannot clobber ``.kicad_pro`` net_settings.

    Snapshots ``<board>.kicad_pro`` before the wrapped save and afterwards
    merges back ``net_settings`` plus any dropped top-level keys (atomic
    write), only when something was lost. No-op when the project file does
    not exist or cannot be parsed. Never raises.
    """
    pro_path = _pro_path_for(board_path or "")
    before: Optional[Dict[str, Any]] = None
    if pro_path and os.path.isfile(pro_path):
        before = _read_json(pro_path)
    try:
        yield
    finally:
        if before is not None and pro_path:
            try:
                after = _read_json(pro_path)
                if after is None:
                    # Save produced no readable project file; restore snapshot.
                    _write_json_atomic(pro_path, before)
                    logger.warning(
                        "Restored %s verbatim: unreadable after board save",
                        pro_path,
                    )
                else:
                    merged, changed = merge_preserved_keys(before, after)
                    if changed:
                        _write_json_atomic(pro_path, merged)
                        logger.info(
                            "Restored preserved .kicad_pro settings "
                            "(net_settings/dropped keys) in %s",
                            pro_path,
                        )
            except Exception as exc:  # never fail the wrapped operation
                logger.warning(
                    "Could not preserve project settings for %s: %s",
                    pro_path,
                    exc,
                )


def snapshot_project_file(board_path: Optional[str]) -> Optional[bytes]:
    """Return the raw bytes of ``<board>.kicad_pro``, or None."""
    pro_path = _pro_path_for(board_path or "")
    if not pro_path or not os.path.isfile(pro_path):
        return None
    try:
        with open(pro_path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def restore_project_file_if_changed(
    board_path: Optional[str], snapshot: Optional[bytes]
) -> bool:
    """Restore ``<board>.kicad_pro`` verbatim if its content changed.

    Used around read-only operations (opening a project must not rewrite
    user settings on disk). Returns True when a restore happened. Never
    raises.
    """
    if snapshot is None:
        return False
    pro_path = _pro_path_for(board_path or "")
    if not pro_path:
        return False
    try:
        current: Optional[bytes]
        try:
            with open(pro_path, "rb") as handle:
                current = handle.read()
        except OSError:
            current = None
        if current == snapshot:
            return False
        directory = os.path.dirname(pro_path) or "."
        fd, tmp_path = tempfile.mkstemp(
            dir=directory, prefix=".prosettings-", suffix=".kicad_pro"
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(snapshot)
            os.replace(tmp_path, pro_path)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
        logger.info(
            "Restored %s verbatim: opening a project must not rewrite it",
            pro_path,
        )
        return True
    except Exception as exc:
        logger.warning("Could not restore project file %s: %s", pro_path, exc)
        return False
