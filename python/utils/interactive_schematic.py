"""Opt-in Windows interactive schematic reload after MCP file edits.

Sends KiCad Schematic Editor Revert (reload from disk) and auto-confirms only
the specific reload/revert dialog. Every window handle is PID-scoped to KiCad;
destructive discard/unsaved dialogs are never auto-confirmed.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Optional

from utils.kicad_process import KiCADProcessManager

logger = logging.getLogger("kicad_interface")

INTERACTIVE_SCHEMATIC = os.environ.get("KICAD_INTERACTIVE_SCHEMATIC", "false").lower() == "true"

if INTERACTIVE_SCHEMATIC:
    logger.info("KiCAD interactive schematic reload enabled (KICAD_INTERACTIVE_SCHEMATIC=true)")

REVERT_CMD_ID = 20236

# Affirmative labels for reload-from-disk confirmation only.
_AFFIRMATIVE_LABELS = frozenset(
    {
        "Yes",
        "&Yes",
        "OK",
        "&OK",
        "Ja",
        "&Ja",
        "Oui",
        "&Oui",
        "Reload",
        "&Reload",
        "Neu laden",
        "&Neu laden",
    }
)

# Never auto-click these — data-loss risk (#194 / #244).
_DESTRUCTIVE_LABELS = frozenset(
    {
        "Discard",
        "&Discard",
        "Discard Changes",
        "Don't Save",
        "Do Not Save",
        "Do not save",
        "No",
        "&No",
        "Cancel",
        "&Cancel",
        "Abort",
        "&Abort",
        "Verwerfen",
        "&Verwerfen",
        "Nicht speichern",
    }
)

_GENERIC_ONLY_TITLES = frozenset(
    {
        "Warning",
        "Information",
        "Confirmation",
        "Warnung",
        "Information",
        "Bestätigung",
        "KiCad",
    }
)

# Main editor frames — not modal reload confirmations.
_MAIN_WINDOW_TITLE_MARKERS = (
    "Schematic Editor",
    "eeschema",
)

# Title must match at least one reload-specific keyword (case-insensitive).
_RELOAD_TITLE_KEYWORDS = re.compile(
    r"(reload|revert|modified|changed|file change|"
    r"neu laden|geändert|aktualis|reload schematic|schematic file|schematic modified)",
    re.IGNORECASE,
)

# Title keywords that indicate a discard-unsaved-work dialog — never auto-confirm.
_DESTRUCTIVE_TITLE_KEYWORDS = re.compile(
    r"(discard|unsaved|verwerfen|nicht speichern|lose changes|without saving)",
    re.IGNORECASE,
)


def is_reload_confirmation_title(title: str) -> bool:
    """True when title looks like a schematic reload/revert prompt, not a generic dialog."""
    if not title or not title.strip():
        return False
    if title.strip() in _GENERIC_ONLY_TITLES:
        return False
    if any(marker in title for marker in _MAIN_WINDOW_TITLE_MARKERS):
        return False
    if _DESTRUCTIVE_TITLE_KEYWORDS.search(title):
        return False
    return bool(_RELOAD_TITLE_KEYWORDS.search(title))


def has_destructive_button(labels: list[str]) -> bool:
    return any(label in _DESTRUCTIVE_LABELS for label in labels)


def choose_affirmative_button(labels: list[str]) -> Optional[str]:
    for label in labels:
        if label in _AFFIRMATIVE_LABELS:
            return label
    return None


def reload_kicad_schematic() -> None:
    """Reload open Schematic Editor from disk after an external MCP edit (Windows, opt-in)."""
    if not INTERACTIVE_SCHEMATIC:
        return
    if os.name != "nt":
        return

    try:
        import win32api
        import win32con
        import win32gui
        import win32process
    except ImportError:
        logger.warning("pywin32 not available — interactive schematic reload disabled")
        return

    kicad_pids = KiCADProcessManager.get_running_pids()
    if not kicad_pids:
        logger.debug("reload_kicad_schematic: no KiCad process found")
        return

    def _hwnd_pid(hwnd: int) -> int:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return pid

    def _owned_by_kicad(hwnd: int) -> bool:
        try:
            return _hwnd_pid(hwnd) in kicad_pids
        except Exception:
            return False

    def _button_labels(hwnd: int) -> list[str]:
        labels: list[str] = []

        def _visit(child: int, _: object) -> None:
            try:
                text = win32gui.GetWindowText(child)
                if text:
                    labels.append(text)
            except Exception:
                pass

        try:
            win32gui.EnumChildWindows(hwnd, _visit, None)
        except Exception:
            pass
        return labels

    def _try_confirm_reload_dialog(hwnd: int, title: str) -> bool:
        if not is_reload_confirmation_title(title):
            return False
        labels = _button_labels(hwnd)
        if has_destructive_button(labels):
            logger.warning(
                "reload_kicad_schematic: refusing auto-confirm on destructive dialog "
                f"'{title}' (buttons={labels!r})"
            )
            return False
        affirmative = choose_affirmative_button(labels)
        if not affirmative:
            logger.debug(
                f"reload_kicad_schematic: reload dialog '{title}' has no safe affirmative "
                f"button (buttons={labels!r})"
            )
            return False
        for child in _iter_child_buttons(hwnd):
            if win32gui.GetWindowText(child) == affirmative:
                win32api.PostMessage(child, win32con.BM_CLICK, 0, 0)
                logger.info(
                    f"reload_kicad_schematic: confirmed reload dialog '{title}' "
                    f"via '{affirmative}' hwnd={hex(hwnd)}"
                )
                return True
        return False

    def _iter_child_buttons(hwnd: int):
        buttons: list[int] = []

        def _visit(child: int, _: object) -> None:
            buttons.append(child)

        try:
            win32gui.EnumChildWindows(hwnd, _visit, None)
        except Exception:
            pass
        return buttons

    def _scan_reload_dialogs(skip_hwnd: Optional[int] = None) -> bool:
        confirmed = False

        def _check(hwnd: int, _: object) -> None:
            nonlocal confirmed
            if confirmed or hwnd == skip_hwnd:
                return
            if not win32gui.IsWindowVisible(hwnd) or not _owned_by_kicad(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if _try_confirm_reload_dialog(hwnd, title):
                confirmed = True

        win32gui.EnumWindows(_check, None)
        return confirmed

    schematic_hwnd: Optional[int] = None

    def _find_schematic(hwnd: int, _: object) -> None:
        nonlocal schematic_hwnd
        if schematic_hwnd is not None or not _owned_by_kicad(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if "Schematic Editor" in title or title.lower() == "eeschema":
            schematic_hwnd = hwnd

    win32gui.EnumWindows(_find_schematic, None)
    if schematic_hwnd is None:
        logger.debug("reload_kicad_schematic: Schematic Editor window not found")
        return

    win32api.PostMessage(schematic_hwnd, win32con.WM_COMMAND, REVERT_CMD_ID, 0)
    logger.info(f"reload_kicad_schematic: sent Revert to hwnd={hex(schematic_hwnd)}")

    for _ in range(8):
        time.sleep(0.15)
        if _scan_reload_dialogs(skip_hwnd=schematic_hwnd):
            return

    logger.debug("reload_kicad_schematic: no reload confirmation dialog appeared after Revert")
