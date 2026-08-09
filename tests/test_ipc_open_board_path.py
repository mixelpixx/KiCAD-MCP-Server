"""Regression tests for IPCBackend.get_open_board_path (kipy DocumentSpecifier shape).

Two independent defects made this method return None even when the live KiCad GUI
had a board open:

1. ``get_open_documents()`` was called with no argument, but kipy's signature is
   ``get_open_documents(self, doc_type)`` — the call raised TypeError, which the
   surrounding ``except Exception`` swallowed at debug level.
2. The returned DocumentSpecifier has ``board_filename`` and ``project.path``; it
   has NO ``.path`` attribute, so the ``hasattr(doc, "path")`` guard never matched.

Because ``_pin_session_backend`` pins "ipc" only when ``get_open_board_path()``
matches the session board, a None return silently pinned every session to SWIG —
losing realtime UI sync with no user-visible error.
"""

import sys
import types
from pathlib import Path
from typing import Any, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

from kicad_api.ipc_backend import IPCBackend  # noqa: E402

DOCTYPE_PCB = 2


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class _FakeProject:
    def __init__(self, path: str) -> None:
        self.path = path


class _FakeDocumentSpecifier:
    """Mirrors kipy's DocumentSpecifier: board_filename + project, and NO `.path`."""

    def __init__(self, board_filename: str, project_path: str) -> None:
        self.board_filename = board_filename
        self.project = _FakeProject(project_path)


class _FakeKiCad:
    """Stands in for kipy.KiCad; doc_type is REQUIRED, exactly as upstream."""

    def __init__(self, docs: List[Any]) -> None:
        self._docs = docs
        self.doc_types_requested: List[int] = []

    def ping(self) -> None:
        return None

    def get_open_documents(self, doc_type: int) -> List[Any]:
        self.doc_types_requested.append(doc_type)
        return list(self._docs)


def _install_fake_kipy(monkeypatch: Any) -> None:
    """Resolve `from kipy.proto.common.types import DocumentType` without real kipy."""
    types_mod = types.ModuleType("kipy.proto.common.types")
    types_mod.DocumentType = types.SimpleNamespace(DOCTYPE_PCB=DOCTYPE_PCB)
    for name, mod in (
        ("kipy", types.ModuleType("kipy")),
        ("kipy.proto", types.ModuleType("kipy.proto")),
        ("kipy.proto.common", types.ModuleType("kipy.proto.common")),
        ("kipy.proto.common.types", types_mod),
    ):
        monkeypatch.setitem(sys.modules, name, mod)


def _make_backend(docs: List[Any]) -> IPCBackend:
    backend = IPCBackend()
    backend._kicad = _FakeKiCad(docs)
    backend._connected = True
    return backend


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_returns_full_path_composed_from_project_and_filename(monkeypatch: Any) -> None:
    """The board path is project.path + board_filename, not a `.path` attribute."""
    _install_fake_kipy(monkeypatch)
    backend = _make_backend([_FakeDocumentSpecifier("DankroRunner.kicad_pcb", "/home/u/proj/pcb")])

    assert backend.get_open_board_path() == "/home/u/proj/pcb/DankroRunner.kicad_pcb"


def test_requests_pcb_document_type_explicitly(monkeypatch: Any) -> None:
    """A no-arg get_open_documents() raises TypeError upstream; assert we pass doc_type."""
    _install_fake_kipy(monkeypatch)
    backend = _make_backend([_FakeDocumentSpecifier("b.kicad_pcb", "/p")])

    backend.get_open_board_path()

    assert backend._kicad.doc_types_requested == [DOCTYPE_PCB]


def test_document_specifier_has_no_path_attribute(monkeypatch: Any) -> None:
    """Guard the shape assumption that caused the original bug."""
    doc = _FakeDocumentSpecifier("b.kicad_pcb", "/p")

    assert not hasattr(doc, "path")


def test_returns_none_when_no_document_open(monkeypatch: Any) -> None:
    _install_fake_kipy(monkeypatch)
    backend = _make_backend([])

    assert backend.get_open_board_path() is None


def test_ignores_non_pcb_documents(monkeypatch: Any) -> None:
    _install_fake_kipy(monkeypatch)
    backend = _make_backend([_FakeDocumentSpecifier("sheet.kicad_sch", "/p")])

    assert backend.get_open_board_path() is None


def test_falls_back_to_bare_filename_when_project_path_empty(monkeypatch: Any) -> None:
    """An unsaved/pathless project must not yield a path with a leading separator."""
    _install_fake_kipy(monkeypatch)
    backend = _make_backend([_FakeDocumentSpecifier("b.kicad_pcb", "")])

    assert backend.get_open_board_path() == "b.kicad_pcb"


def test_returns_none_when_not_connected(monkeypatch: Any) -> None:
    _install_fake_kipy(monkeypatch)
    backend = IPCBackend()

    assert backend.get_open_board_path() is None
