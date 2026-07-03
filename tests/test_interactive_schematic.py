"""Tests for opt-in interactive schematic reload helpers."""

from utils.interactive_schematic import (
    choose_affirmative_button,
    has_destructive_button,
    is_reload_confirmation_title,
)


def test_reload_title_accepts_specific_prompts() -> None:
    assert is_reload_confirmation_title("Schematic file modified — reload?")
    assert is_reload_confirmation_title("Reload schematic from disk")
    assert is_reload_confirmation_title("Datei geändert — neu laden")


def test_reload_title_rejects_generic_or_destructive() -> None:
    assert not is_reload_confirmation_title("Warning")
    assert not is_reload_confirmation_title("Information")
    assert not is_reload_confirmation_title("Confirmation")
    assert not is_reload_confirmation_title("Discard unsaved changes?")
    assert not is_reload_confirmation_title("Save changes before closing?")
    assert not is_reload_confirmation_title("* FOG.kicad_sch - Schematic Editor")
    assert not is_reload_confirmation_title("eeschema")


def test_destructive_buttons_block_auto_confirm() -> None:
    assert has_destructive_button(["Discard", "Cancel"])
    assert has_destructive_button(["Yes", "No"])
    assert not has_destructive_button(["Yes", "OK"])
    assert choose_affirmative_button(["Cancel", "Reload"]) == "Reload"
    assert choose_affirmative_button(["Discard", "Cancel"]) is None
