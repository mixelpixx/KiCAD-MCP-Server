"""Compatibility tests for kicad-python PCB document discovery."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_api.ipc_backend import IPCBackend

pytestmark = pytest.mark.unit
kipy_types = pytest.importorskip("kipy.proto.common.types")
DocumentSpecifier = kipy_types.DocumentSpecifier
DocumentType = kipy_types.DocumentType


class FakeKiCad:
    def __init__(self, documents):
        self.documents = documents
        self.requested_types = []

    def get_open_documents(self, document_type):
        self.requested_types.append(document_type)
        return self.documents

    def ping(self):
        return None


def connected_backend(documents):
    backend = IPCBackend()
    backend._connected = True
    backend._kicad = FakeKiCad(documents)
    return backend


def test_get_open_board_path_uses_filtered_document_api(tmp_path):
    document = DocumentSpecifier()
    document.type = DocumentType.DOCTYPE_PCB
    document.board_filename = "board.kicad_pcb"
    document.project.path = str(tmp_path)
    backend = connected_backend([document])

    assert backend.get_open_board_path() == str(tmp_path / "board.kicad_pcb")
    assert backend._kicad.requested_types == [DocumentType.DOCTYPE_PCB]


def test_get_open_board_path_supports_legacy_path_field(tmp_path):
    expected = tmp_path / "legacy.kicad_pcb"
    document = SimpleNamespace(path=str(expected))
    backend = connected_backend([document])

    assert backend.get_open_board_path() == str(expected)


def test_get_open_board_path_returns_none_when_no_board_is_open():
    backend = connected_backend([])

    assert backend.get_open_board_path() is None


def test_document_path_preserves_absolute_board_filename(tmp_path):
    expected = tmp_path / "absolute.kicad_pcb"
    document = SimpleNamespace(
        board_filename=str(expected),
        project=SimpleNamespace(path=str(Path("ignored"))),
    )

    assert IPCBackend._document_path(document) == str(expected)
