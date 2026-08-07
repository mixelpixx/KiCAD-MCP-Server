"""Tests for request correlation on the TypeScript/Python bridge."""

from kicad_interface import _attach_internal_request_id


def test_attach_internal_request_id_returns_a_decorated_copy():
    response = {"success": True, "value": "ok"}

    decorated = _attach_internal_request_id(response, 42)

    assert decorated == {"success": True, "value": "ok", "_requestId": 42}
    assert response == {"success": True, "value": "ok"}


def test_attach_internal_request_id_leaves_uncorrelated_responses_unchanged():
    response = {"type": "ready"}

    assert _attach_internal_request_id(response, None) is response
