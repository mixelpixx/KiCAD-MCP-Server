"""Security regression tests for the authenticated JLCPCB client."""

import logging
import sys
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).resolve().parent.parent / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from commands import jlcpcb  # noqa: E402


def test_authorization_secrets_are_not_logged(caplog, monkeypatch):
    client = jlcpcb.JLCPCBClient(
        app_id="secret-app-id",
        access_key="secret-access-key",
        secret_key="secret-signing-key",
    )
    monkeypatch.setattr(client, "_generate_nonce", lambda: "secret-nonce")
    monkeypatch.setattr(jlcpcb.time, "time", lambda: 1_700_000_000)

    with caplog.at_level(logging.DEBUG, logger="kicad_interface"):
        header = client._get_auth_header("POST", "/component/getComponentInfos", "{}")

    # The credentials still reach the request header, but none of the material
    # used to construct that header may be written to logs.
    assert "secret-access-key" in header
    assert "secret-app-id" in header
    assert "secret-app-id" not in caplog.text
    assert "secret-access-key" not in caplog.text
    assert "secret-signing-key" not in caplog.text
    assert "secret-nonce" not in caplog.text
    assert "signature=" not in caplog.text


def test_response_body_and_headers_are_not_logged(caplog, monkeypatch):
    class Response:
        status_code = 200
        is_redirect = False
        headers = {"X-Account-Debug": "secret-response-header"}
        text = "secret-response-body"

        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"code": 200, "data": {"componentInfos": [], "lastKey": None}}

    monkeypatch.setattr(jlcpcb.requests, "post", lambda *args, **kwargs: Response())
    client = jlcpcb.JLCPCBClient("app", "access", "signing")

    with caplog.at_level(logging.DEBUG, logger="kicad_interface"):
        client.fetch_parts_page()

    assert "secret-response-header" not in caplog.text
    assert "secret-response-body" not in caplog.text


def test_authenticated_request_does_not_follow_redirects(monkeypatch):
    captured = {}

    class Response:
        status_code = 302
        is_redirect = True

    def _post(*args, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(jlcpcb.requests, "post", _post)
    client = jlcpcb.JLCPCBClient("app", "access", "signing")

    with pytest.raises(Exception, match="unexpectedly returned a redirect"):
        client.fetch_parts_page()

    assert captured["allow_redirects"] is False


def test_full_catalog_download_discards_partial_pages(monkeypatch):
    client = jlcpcb.JLCPCBClient("app", "access", "signing")
    responses = iter(
        [
            {"componentInfos": [{"componentCode": "C1"}], "lastKey": "next"},
            RuntimeError("page failed"),
        ]
    )

    def fetch_page(_last_key=None):
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(client, "fetch_parts_page", fetch_page)
    monkeypatch.setattr(jlcpcb.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="page 2 after 1 parts; partial data was discarded"):
        client.download_full_database()
