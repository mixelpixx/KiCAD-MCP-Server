"""Tests for the unified KiCad install-root discovery (utils.kicad_roots).

Issue #286: three modules independently assumed KiCad lived under Program Files
on Windows, so a custom install root (e.g. C:\\KiCad\\10.0) or a registry-only
install got degraded cli/symbol/footprint discovery. utils.kicad_roots is the
single source of truth they now share.

The registry walk is exercised through a fake ``winreg`` module so these tests
run on any platform (CI is Linux, where the real ``winreg`` does not exist).
"""

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import kicad_mcp.utils as utils.kicad_roots as kr  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_roots_cache():
    """Install roots are cached per-process; reset around each test so a fake
    registry/glob in one test cannot leak into the next."""
    kr.reset_cache()
    yield
    kr.reset_cache()


# --------------------------------------------------------------------------- #
# _version_key — pure parsing/ordering helper
# --------------------------------------------------------------------------- #


class TestVersionKey:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("10.0.4", (10, 0, 4)),
            ("9.0.3", (9, 0, 3)),
            ("10.0", (10, 0, 0)),
            ("KiCad 9.0", (9, 0, 0)),
            ("8", (8, 0, 0)),
            ("", (0, 0, 0)),
            ("nightly", (0, 0, 0)),
        ],
    )
    def test_parses_version(self, text, expected):
        assert kr._version_key(text) == expected

    def test_newer_sorts_higher(self):
        assert kr._version_key("10.0.4") > kr._version_key("9.0.3")


# --------------------------------------------------------------------------- #
# Fake winreg so _registry_roots is testable off-Windows
# --------------------------------------------------------------------------- #


class _FakeKey:
    def __init__(self, subkeys=None, values=None):
        self.subkeys = subkeys or {}  # name -> _FakeKey
        self.values = values or {}  # name -> value


def _make_fake_winreg(hive_trees):
    """Build a stand-in ``winreg`` module.

    ``hive_trees`` maps ``(hive, subpath)`` to a dict of
    ``{uninstall_subkey_name: {value_name: value}}``.
    """
    mod = types.ModuleType("winreg")
    mod.HKEY_LOCAL_MACHINE = "HKLM"
    mod.HKEY_CURRENT_USER = "HKCU"

    roots = {}
    for (hive, subpath), entries in hive_trees.items():
        subkeys = {name: _FakeKey(values=vals) for name, vals in entries.items()}
        roots[(hive, subpath)] = _FakeKey(subkeys=subkeys)

    def OpenKey(key, sub=None):
        # Base open: OpenKey(hive, subpath)
        if isinstance(key, str):
            try:
                return roots[(key, sub)]
            except KeyError:
                raise OSError("no such key")
        # Child open: OpenKey(parentKey, subname)
        try:
            return key.subkeys[sub]
        except KeyError:
            raise OSError("no such subkey")

    def QueryInfoKey(key):
        return (len(key.subkeys), 0, 0)

    def EnumKey(key, index):
        return list(key.subkeys.keys())[index]

    def QueryValueEx(key, name):
        try:
            return (key.values[name], 1)
        except KeyError:
            raise OSError("no such value")

    mod.OpenKey = OpenKey
    mod.QueryInfoKey = QueryInfoKey
    mod.EnumKey = EnumKey
    mod.QueryValueEx = QueryValueEx
    return mod


@pytest.fixture
def as_windows(monkeypatch):
    """Force the module to take its Windows path."""
    monkeypatch.setattr(kr.platform, "system", lambda: "Windows")


def _install(tmp_path, name):
    """Create a fake install root directory and return its Path."""
    root = tmp_path / name
    (root / "bin").mkdir(parents=True)
    return root


# --------------------------------------------------------------------------- #
# _registry_roots
# --------------------------------------------------------------------------- #


class TestRegistryRoots:
    def test_finds_kicad_entries_and_ignores_others(self, tmp_path, monkeypatch, as_windows):
        k10 = _install(tmp_path, "KiCad10")
        k9 = _install(tmp_path, "KiCad9")
        base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
        fake = _make_fake_winreg(
            {
                ("HKLM", base): {
                    "KiCad 10.0": {
                        "DisplayName": "KiCad 10.0",
                        "DisplayVersion": "10.0.4",
                        "InstallLocation": str(k10),
                    },
                    "KiCad 9.0": {
                        "DisplayName": "KiCad 9.0",
                        "DisplayVersion": "9.0.3",
                        "InstallLocation": str(k9),
                    },
                    "SomeOtherApp": {
                        "DisplayName": "Notepad++",
                        "InstallLocation": str(tmp_path / "npp"),
                    },
                }
            }
        )
        monkeypatch.setitem(sys.modules, "winreg", fake)

        found = kr._registry_roots()
        paths = {p for _, p in found}
        assert k10 in paths
        assert k9 in paths
        assert (tmp_path / "npp") not in paths  # non-KiCad ignored

    def test_skips_entry_without_install_location(self, tmp_path, monkeypatch, as_windows):
        base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
        fake = _make_fake_winreg(
            {
                ("HKLM", base): {
                    "KiCad 10.0": {  # no InstallLocation
                        "DisplayName": "KiCad 10.0",
                        "DisplayVersion": "10.0.4",
                    },
                }
            }
        )
        monkeypatch.setitem(sys.modules, "winreg", fake)
        assert kr._registry_roots() == []

    def test_skips_nonexistent_install_location(self, tmp_path, monkeypatch, as_windows):
        base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
        fake = _make_fake_winreg(
            {
                ("HKLM", base): {
                    "KiCad 10.0": {
                        "DisplayName": "KiCad 10.0",
                        "DisplayVersion": "10.0.4",
                        "InstallLocation": str(tmp_path / "gone"),
                    },
                }
            }
        )
        monkeypatch.setitem(sys.modules, "winreg", fake)
        assert kr._registry_roots() == []

    def test_non_windows_returns_empty(self, monkeypatch):
        monkeypatch.setattr(kr.platform, "system", lambda: "Linux")
        assert kr._registry_roots() == []


# --------------------------------------------------------------------------- #
# windows_kicad_roots — merge, order, dedup
# --------------------------------------------------------------------------- #


class TestWindowsRootsMerge:
    def test_newest_first_and_deduped(self, tmp_path, monkeypatch, as_windows):
        k10 = _install(tmp_path, "KiCad10")
        k9 = _install(tmp_path, "KiCad9")
        # Registry reports 10.0.4 and 9.0.3; glob re-reports the same 10.0 root
        # (as it would for a Program Files install also in the registry).
        monkeypatch.setattr(kr, "_registry_roots", lambda: [((10, 0, 4), k10), ((9, 0, 3), k9)])
        monkeypatch.setattr(kr, "_glob_roots", lambda: [((10, 0, 0), k10)])

        roots = kr.windows_kicad_roots()
        assert roots == [k10, k9]  # newest first, k10 appears once

    def test_custom_root_surfaces(self, tmp_path, monkeypatch, as_windows):
        custom = _install(tmp_path, "KiCad")  # e.g. C:\KiCad\10.0 shape
        monkeypatch.setattr(kr, "_registry_roots", lambda: [])
        monkeypatch.setattr(kr, "_glob_roots", lambda: [((10, 0, 0), custom)])
        assert kr.windows_kicad_roots() == [custom]

    def test_dedup_is_case_insensitive(self, tmp_path, monkeypatch, as_windows):
        root = _install(tmp_path, "KiCad10")
        upper = Path(str(root).upper())
        monkeypatch.setattr(kr, "_registry_roots", lambda: [((10, 0, 4), root)])
        monkeypatch.setattr(kr, "_glob_roots", lambda: [((10, 0, 0), upper)])
        # normcase collapses the two spellings to one entry.
        assert len(kr.windows_kicad_roots()) == 1


# --------------------------------------------------------------------------- #
# kicad_install_roots — public entry
# --------------------------------------------------------------------------- #


class TestPublicEntry:
    def test_non_windows_returns_empty(self, monkeypatch):
        monkeypatch.setattr(kr.platform, "system", lambda: "Darwin")
        assert kr.kicad_install_roots() == []

    @pytest.mark.skipif(
        __import__("platform").system() != "Windows", reason="real install layout is Windows-only"
    )
    def test_real_machine_roots_exist(self):
        # On a real Windows box every discovered root must be an existing dir
        # containing bin/ (empty is fine — KiCad may not be installed in CI).
        for root in kr.kicad_install_roots():
            assert root.is_dir(), root
