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

import utils.kicad_roots as kr  # noqa: E402


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
    """Force the module to take its Windows path.

    Also simulates Windows path-case semantics. The dedup in
    ``_merge_roots`` relies on ``os.path.normcase`` folding case, which it
    only does on Windows — on POSIX it is the identity function, so
    differently-cased spellings of one root stay distinct and the dedup
    assertions fail on Linux CI for a reason that cannot occur in
    production (these code paths are guarded by a platform check).
    """
    monkeypatch.setattr(kr.platform, "system", lambda: "Windows")
    monkeypatch.setattr(kr.os.path, "normcase", lambda p: str(p).lower())


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


# --------------------------------------------------------------------------- #
# macos_kicad_apps / reroot_kicad_app_path (#543)
# --------------------------------------------------------------------------- #


def _make_bundle(base: Path, *parts: str) -> Path:
    """Create a fake KiCad.app bundle directory and return its Path."""
    bundle = base.joinpath(*parts)
    (bundle / "Contents" / "MacOS").mkdir(parents=True)
    return bundle


@pytest.fixture
def as_darwin(monkeypatch):
    """Force the module to take its macOS path."""
    monkeypatch.setattr(kr.platform, "system", lambda: "Darwin")


@pytest.fixture
def plain_python(tmp_path, monkeypatch):
    """An interpreter outside any KiCad.app (executable and base prefix)."""
    monkeypatch.setattr(kr.sys, "executable", str(tmp_path / "bin" / "python3"))
    monkeypatch.setattr(kr.sys, "base_prefix", str(tmp_path))


class TestMacosBundleCandidates:
    def test_interpreter_bundle_comes_first(self, tmp_path, monkeypatch, as_darwin, plain_python):
        mine = _make_bundle(tmp_path, "KiCad.app")
        monkeypatch.setattr(kr.sys, "executable", str(mine / "Contents" / "MacOS" / "python3"))
        assert kr._macos_bundle_candidates()[0] == mine

    def test_venv_symlink_into_bundle_comes_first(
        self, tmp_path, monkeypatch, as_darwin, plain_python
    ):
        """A venv built on KiCad's Python: sys.executable is the venv's
        bin/python, a symlink to the interpreter inside the bundle."""
        mine = _make_bundle(tmp_path, "KiCad.app")
        real = mine / "Contents" / "MacOS" / "python3"
        real.write_text("", encoding="utf-8")
        venv_bin = tmp_path / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        link = venv_bin / "python"
        try:
            link.symlink_to(real)
        except OSError:
            pytest.skip("symlinks not available")
        monkeypatch.setattr(kr.sys, "executable", str(link))
        assert kr._macos_bundle_candidates()[0] == mine.resolve()

    def test_base_prefix_bundle_comes_first(self, tmp_path, monkeypatch, as_darwin, plain_python):
        mine = _make_bundle(tmp_path, "KiCad.app")
        framework = mine / "Contents" / "Frameworks" / "Python.framework" / "Versions" / "3.9"
        monkeypatch.setattr(kr.sys, "base_prefix", str(framework))
        assert kr._macos_bundle_candidates()[0] == mine

    def test_no_app_ancestor_means_dmg_layout_first(self, as_darwin, plain_python):
        assert kr._macos_bundle_candidates()[0] == Path("/Applications/KiCad/KiCad.app")

    def test_candidate_order(self, as_darwin, plain_python):
        home = Path.home()
        assert kr._macos_bundle_candidates() == [
            Path("/Applications/KiCad/KiCad.app"),
            Path("/Applications/KiCad.app"),
            home / "Applications" / "KiCad" / "KiCad.app",
            home / "Applications" / "KiCad.app",
            Path("/Applications/KiCAD/KiCad.app"),
            home / "Applications" / "KiCad" / "KiCAD.app",
        ]


class TestMacosKicadApps:
    def test_non_darwin_returns_empty(self, monkeypatch):
        monkeypatch.setattr(kr.platform, "system", lambda: "Linux")
        assert kr.macos_kicad_apps() == []

    def test_only_existing_bundles_in_order(self, tmp_path, monkeypatch, as_darwin):
        dmg = _make_bundle(tmp_path, "KiCad", "KiCad.app")
        flat = _make_bundle(tmp_path, "KiCad.app")
        monkeypatch.setattr(
            kr, "_macos_bundle_candidates", lambda: [flat, dmg, tmp_path / "gone.app", flat]
        )
        assert kr.macos_kicad_apps() == [flat, dmg]

    def test_two_spellings_of_one_directory_deduped(self, tmp_path, monkeypatch, as_darwin):
        """On a case-insensitive filesystem (default APFS, NTFS) KiCad/KiCAD
        name one directory; neither normcase nor resolve() folds case on macOS."""
        bundle = _make_bundle(tmp_path, "KiCad", "KiCad.app")
        other_spelling = tmp_path / "KiCAD" / "KiCad.app"
        if not other_spelling.is_dir():
            pytest.skip("case-sensitive filesystem")
        monkeypatch.setattr(kr, "_macos_bundle_candidates", lambda: [bundle, other_spelling])
        assert kr.macos_kicad_apps() == [bundle]

    def test_same_inode_deduped(self, tmp_path, monkeypatch, as_darwin):
        """De-duplication keys on (st_dev, st_ino), not on the path text."""
        bundle = _make_bundle(tmp_path, "KiCad.app")
        other = _make_bundle(tmp_path, "KiCAD.app")
        real_stat = Path.stat

        def fake_stat(self, *args, **kwargs):
            # Make the second spelling report the first one's identity, as a
            # case-insensitive filesystem does.
            return real_stat(bundle if self == other else self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", fake_stat)
        monkeypatch.setattr(kr, "_macos_bundle_candidates", lambda: [bundle, other])
        assert kr.macos_kicad_apps() == [bundle]

    def test_reset_cache_clears_macos_apps(self, tmp_path, monkeypatch, as_darwin):
        first = _make_bundle(tmp_path, "KiCad.app")
        second = _make_bundle(tmp_path, "KiCad", "KiCad.app")
        monkeypatch.setattr(kr, "_macos_bundle_candidates", lambda: [first])
        assert kr.macos_kicad_apps() == [first]
        monkeypatch.setattr(kr, "_macos_bundle_candidates", lambda: [second])
        assert kr.macos_kicad_apps() == [first]  # cached
        kr.reset_cache()
        assert kr.macos_kicad_apps() == [second]

    def test_symlinked_spelling_deduped(self, tmp_path, monkeypatch, as_darwin):
        bundle = _make_bundle(tmp_path, "KiCad.app")
        alias = tmp_path / "Alias.app"
        alias.symlink_to(bundle, target_is_directory=True)
        monkeypatch.setattr(kr, "_macos_bundle_candidates", lambda: [bundle, alias])
        assert kr.macos_kicad_apps() == [bundle]


class TestRerootKicadAppPath:
    def test_reroots_missing_bundle_onto_installed(self, tmp_path, monkeypatch, as_darwin):
        installed = _make_bundle(tmp_path, "KiCad.app")
        monkeypatch.setattr(kr, "macos_kicad_apps", lambda: [installed])
        # The stale bundle is built under tmp_path so a real DMG install on
        # the test machine cannot make it exist.
        old = tmp_path / "Old" / "KiCad" / "KiCad.app" / "Contents" / "SharedSupport"
        old = old / "symbols" / "Device.kicad_sym"
        assert kr.reroot_kicad_app_path(old) == [
            installed / "Contents" / "SharedSupport" / "symbols" / "Device.kicad_sym"
        ]

    def test_existing_bundle_is_not_rerooted(self, tmp_path, monkeypatch, as_darwin):
        bundle = _make_bundle(tmp_path, "KiCad", "KiCad.app")
        monkeypatch.setattr(kr, "macos_kicad_apps", lambda: [bundle])
        path = bundle / "Contents" / "SharedSupport" / "symbols" / "Device.kicad_sym"
        assert kr.reroot_kicad_app_path(path) == []

    def test_paths_without_an_app_segment_return_empty(self, tmp_path, monkeypatch, as_darwin):
        assert kr.reroot_kicad_app_path(tmp_path / "foo" / "bar") == []
        assert kr.reroot_kicad_app_path(tmp_path / "Old" / "KiCad" / "KiCad.app") == []
