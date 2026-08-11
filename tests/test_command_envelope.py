"""Tests for the private TypeScript-to-Python command envelope."""

import json
import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

import kicad_interface
from kicad_interface import _process_command_envelope, _write_response


def test_command_envelope_echoes_request_id_and_dispatches() -> None:
    interface = Mock()
    interface.handle_command.return_value = {"success": True, "value": 42}

    response = _process_command_envelope(
        interface,
        {"requestId": "req-17", "command": "get_board_info", "params": {"unit": "mm"}},
    )

    assert response == {"success": True, "value": 42, "requestId": "req-17"}
    interface.handle_command.assert_called_once_with("get_board_info", {"unit": "mm"})


def test_command_envelope_rejects_non_string_request_id() -> None:
    interface = Mock()
    interface.handle_command.return_value = {"success": False, "requestId": "stale"}

    response = _process_command_envelope(
        interface, {"requestId": 9, "command": "save_project", "params": {}}
    )

    assert response["requestId"] == 9
    assert response["success"] is False
    assert response["message"] == "Invalid request ID"
    interface.handle_command.assert_not_called()


def test_command_envelope_rejects_direct_mcp_jsonrpc() -> None:
    interface = Mock()

    response = _process_command_envelope(
        interface,
        {"requestId": "req-18", "jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )

    assert response["success"] is False
    assert response["requestId"] == "req-18"
    assert "not supported" in response["message"]
    interface.handle_command.assert_not_called()


def test_command_envelope_validates_command_and_params() -> None:
    interface = Mock()

    missing = _process_command_envelope(interface, {"requestId": "missing", "params": {}})
    invalid_params = _process_command_envelope(
        interface, {"requestId": "params", "command": "get_board_info", "params": []}
    )

    assert missing["message"] == "Missing command"
    assert missing["requestId"] == "missing"
    assert invalid_params["message"] == "Invalid command parameters"
    assert invalid_params["requestId"] == "params"
    interface.handle_command.assert_not_called()


def test_response_writer_retries_partial_pipe_writes(monkeypatch) -> None:
    written_chunks = []

    def partial_write(response_fd, payload):
        assert response_fd == 17
        chunk = bytes(payload[: max(1, len(payload) // 2)])
        written_chunks.append(chunk)
        return len(chunk)

    monkeypatch.setattr(kicad_interface.os, "write", partial_write)

    response = {"requestId": "req-large", "success": True, "values": list(range(20))}
    _write_response(17, response)

    assert len(written_chunks) > 1
    assert b"".join(written_chunks) == (json.dumps(response) + "\n").encode("utf-8")
