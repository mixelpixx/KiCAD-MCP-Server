"""Compatibility tests for kicad-python PCB document discovery."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from kicad_api.ipc_backend import IPCBackend
from kipy.proto.common.types import DocumentSpecifier, DocumentType

pytestmark = pytest.mark.unit


class FakeKiCad:
    def __init__(self, documents):
        self.documents = documents
        self.requested_types = []

    def get_open_documents(self, document_type):
        self.requested_types.append(document_type)
        return self.documents

    def ping(self):
        return None


class LegacyFakeKiCad:
    def __init__(self, documents):
        self.documents = documents
        self.calls = 0

    def get_open_documents(self):
        self.calls += 1
        return self.documents


class FailingTypedKiCad:
    def __init__(self):
        self.requested_types = []

    def get_open_documents(self, document_type):
        self.requested_types.append(document_type)
        raise TypeError("internal protobuf conversion failed")


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


def test_get_open_documents_supports_legacy_zero_argument_adapter():
    kicad = LegacyFakeKiCad(["legacy-document"])

    assert IPCBackend._get_open_pcb_documents(kicad) == ["legacy-document"]
    assert kicad.calls == 1


def test_get_open_documents_preserves_internal_type_error():
    kicad = FailingTypedKiCad()

    with pytest.raises(TypeError, match="internal protobuf conversion failed"):
        IPCBackend._get_open_pcb_documents(kicad)

    assert kicad.requested_types == [DocumentType.DOCTYPE_PCB]


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


def project_document(project_dir: Path, project_name: str = "demo") -> DocumentSpecifier:
    document = DocumentSpecifier()
    document.type = DocumentType.DOCTYPE_PCB
    document.board_filename = f"{project_name}.kicad_pcb"
    document.project.name = project_name
    document.project.path = str(project_dir)
    return document


@pytest.mark.parametrize("requested_kind", ["project", "board", "directory"])
def test_open_project_matches_structured_document_paths(tmp_path, requested_kind):
    document = project_document(tmp_path)
    backend = connected_backend([document])
    requested_paths = {
        "project": tmp_path / "demo.kicad_pro",
        "board": tmp_path / "demo.kicad_pcb",
        "directory": tmp_path,
    }

    result = backend.open_project(requested_paths[requested_kind])

    assert result["success"] is True


def test_open_project_does_not_use_partial_or_formatted_protobuf_matches(tmp_path):
    document = project_document(tmp_path / "demo-project")
    backend = connected_backend([document])

    result = backend.open_project(tmp_path / "demo")

    assert result["success"] is False


def test_open_project_derives_project_filename_when_project_name_is_missing(tmp_path):
    document = project_document(tmp_path)
    document.project.name = ""
    backend = connected_backend([document])

    result = backend.open_project(tmp_path / "demo.kicad_pro")

    assert result["success"] is True
