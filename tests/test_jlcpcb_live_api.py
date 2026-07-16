"""
Unit tests for the real-time JLCPCB Open Platform lookup path.

These tests do NOT hit the network — ``requests.post`` is always mocked and no
real credentials are used. They cover:

  * Authorization header construction (JOP / HMAC-SHA256).
  * ``get_component_detail`` batching, C-prefix normalization, and that codes the
    API doesn't return are simply absent from the result.
  * ``normalize_detail_to_part`` mapping, incl. the ``[{qty, price}]`` price shape
    and libraryType base/expand -> Basic/Extended.
  * ``_load_env_file`` never overriding an already-set env var.
  * ``has_credentials``.
  * The ``get_jlcpcb_part`` handler's live-first-then-local fallback.
"""

import base64
import hashlib
import hmac
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Match the import root used elsewhere in the test suite (python/ on sys.path).
PYTHON_DIR = Path(__file__).resolve().parent.parent / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from commands import jlcpcb  # noqa: E402
from commands.jlcpcb import (  # noqa: E402
    JLCPCBClient,
    _library_type_label,
    _load_env_file,
    normalize_detail_to_part,
)

CREDS = dict(app_id="app-123", access_key="ak-456", secret_key="sk-789")


@pytest.fixture(autouse=True)
def _no_real_env(monkeypatch):
    """Never let a test touch the user's real repo-root .env or ambient creds.

    Neutralizes the constructor's ``_load_env_file()`` call and clears the three
    JLCPCB_* vars so credential state is entirely test-controlled.
    """
    monkeypatch.setattr(jlcpcb, "_load_env_file", lambda *a, **k: None)
    for var in ("JLCPCB_APP_ID", "JLCPCB_API_KEY", "JLCPCB_API_SECRET"):
        monkeypatch.delenv(var, raising=False)


def _client() -> JLCPCBClient:
    return JLCPCBClient(**CREDS)


class _FakeResponse:
    """Minimal stand-in for a ``requests.Response``."""

    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {"J-Trace-ID": "trace-xyz"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


# ---------------------------------------------------------------------------
# Authorization header
# ---------------------------------------------------------------------------


def test_auth_header_construction(monkeypatch):
    client = _client()
    monkeypatch.setattr(client, "_generate_nonce", lambda: "n" * 32)
    monkeypatch.setattr(jlcpcb.time, "time", lambda: 1_700_000_000)

    body = json.dumps({"componentCodes": ["C8734"]}, separators=(",", ":"))
    header = client._get_auth_header("POST", client.DETAIL_PATH, body)

    assert header.startswith("JOP ")
    assert 'appid="app-123"' in header
    assert 'accesskey="ak-456"' in header
    assert 'nonce="nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn"' in header
    assert 'timestamp="1700000000"' in header

    # Signature must match an independently computed HMAC-SHA256 of the canonical
    # "METHOD\npath\ntimestamp\nnonce\nbody\n" string.
    sig_string = f"POST\n{client.DETAIL_PATH}\n1700000000\n{'n' * 32}\n{body}\n"
    expected = base64.b64encode(
        hmac.new(b"sk-789", sig_string.encode(), hashlib.sha256).digest()
    ).decode()
    assert f'signature="{expected}"' in header


# ---------------------------------------------------------------------------
# get_component_detail
# ---------------------------------------------------------------------------


def _install_post_capture(monkeypatch, payload_for):
    """Patch ``requests.post`` to record calls and return payload_for(batch)."""
    calls = []

    def fake_post(url, headers=None, data=None, timeout=None):
        body = json.loads(data)
        calls.append({"url": url, "headers": headers, "body": body})
        return _FakeResponse({"code": 200, "data": payload_for(body["componentCodes"])})

    monkeypatch.setattr(jlcpcb.requests, "post", fake_post)
    return calls


def test_get_component_detail_normalizes_c_prefix(monkeypatch):
    client = _client()
    calls = _install_post_capture(
        monkeypatch, lambda codes: [{"componentCode": c} for c in codes]
    )

    client.get_component_detail(["8734", "c25804", "C100"])

    assert len(calls) == 1
    assert calls[0]["body"]["componentCodes"] == ["C8734", "C25804", "C100"]
    assert calls[0]["url"].endswith(client.DETAIL_PATH)


def test_get_component_detail_batches_over_1000(monkeypatch):
    client = _client()
    calls = _install_post_capture(
        monkeypatch, lambda codes: [{"componentCode": c} for c in codes]
    )

    codes = [f"C{i}" for i in range(2500)]
    result = client.get_component_detail(codes)

    # 2500 codes -> batches of 1000, 1000, 500.
    assert [len(c["body"]["componentCodes"]) for c in calls] == [1000, 1000, 500]
    assert len(result) == 2500


def test_get_component_detail_drops_codes_the_api_omits(monkeypatch):
    client = _client()
    # API only knows C1; C2 is unknown and simply not returned.
    _install_post_capture(
        monkeypatch,
        lambda codes: [{"componentCode": c} for c in codes if c == "C1"],
    )

    result = client.get_component_detail(["C1", "C2"])

    assert [d["componentCode"] for d in result] == ["C1"]


def test_get_component_detail_empty_input_makes_no_call(monkeypatch):
    client = _client()
    calls = _install_post_capture(monkeypatch, lambda codes: [])
    assert client.get_component_detail([]) == []
    assert calls == []


def test_get_component_detail_tolerates_wrapped_volist(monkeypatch):
    client = _client()

    def fake_post(url, headers=None, data=None, timeout=None):
        return _FakeResponse(
            {"code": 200, "data": {"componentDetailResponseVOList": [{"componentCode": "C1"}]}}
        )

    monkeypatch.setattr(jlcpcb.requests, "post", fake_post)
    result = client.get_component_detail(["C1"])
    assert [d["componentCode"] for d in result] == ["C1"]


def test_post_signed_raises_on_api_error_code(monkeypatch):
    client = _client()

    def fake_post(url, headers=None, data=None, timeout=None):
        return _FakeResponse({"code": 500, "message": "boom"})

    monkeypatch.setattr(jlcpcb.requests, "post", fake_post)
    with pytest.raises(Exception) as exc:
        client.get_component_detail(["C1"])
    assert "boom" in str(exc.value)


# ---------------------------------------------------------------------------
# normalize_detail_to_part
# ---------------------------------------------------------------------------

SAMPLE_DETAIL = {
    "componentCode": "C25804",
    "componentModel": "RC0805FR-0710KL",
    "componentSpecification": "0805",
    "firstTypeName": "Resistors",
    "secondTypeName": "Chip Resistor - Surface Mount",
    "libraryType": "base",
    "description": "10kOhms ±1% 0805",
    "datasheetUrl": "https://example.com/ds.pdf",
    "solderJointCount": 2,
    "stockCount": 12345,
    "rohsFlag": True,
    "eccnCode": "EAR99",
    "assemblyComponentFlag": True,
    "priceRanges": [
        {"startQuantity": 1, "endQuantity": 99, "unitPrice": 0.02},
        {"startQuantity": 100, "endQuantity": -1, "unitPrice": 0.01},
    ],
    "parameters": [{"parameterName": "Resistance", "parameterValue": "10kOhms"}],
}


def test_normalize_maps_core_fields():
    part = normalize_detail_to_part(SAMPLE_DETAIL)
    assert part["lcsc"] == "C25804"
    assert part["mfr_part"] == "RC0805FR-0710KL"
    assert part["package"] == "0805"
    assert part["category"] == "Resistors"
    assert part["subcategory"] == "Chip Resistor - Surface Mount"
    assert part["stock"] == 12345
    assert part["datasheet"] == "https://example.com/ds.pdf"
    assert part["source"] == "live-api"


def test_normalize_price_breaks_have_manager_shape():
    part = normalize_detail_to_part(SAMPLE_DETAIL)
    # Same [{qty, price}] shape the TS renderer and local get_part_info use.
    assert part["price_breaks"] == [
        {"qty": 1, "price": 0.02},
        {"qty": 100, "price": 0.01},
    ]
    # price_json is a JSON string of the same list.
    assert json.loads(part["price_json"]) == part["price_breaks"]
    # Full tiers preserved separately.
    assert part["price_ranges"] == SAMPLE_DETAIL["priceRanges"]


def test_normalize_price_breaks_skip_null_prices():
    detail = {"priceRanges": [{"startQuantity": 1, "unitPrice": None}, {"startQuantity": 10, "unitPrice": 0.5}]}
    part = normalize_detail_to_part(detail)
    assert part["price_breaks"] == [{"qty": 10, "price": 0.5}]


def test_normalize_missing_manufacturer_is_empty_string():
    # The detail response has no manufacturer field.
    part = normalize_detail_to_part(SAMPLE_DETAIL)
    assert part["manufacturer"] == ""


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("base", "Basic"),
        ("Basic", "Basic"),
        ("expand", "Extended"),
        ("Extended", "Extended"),
        ("preferred", "Preferred"),
        ("something-else", "Extended"),
        (None, "Extended"),
    ],
)
def test_library_type_label(raw, expected):
    assert _library_type_label(raw) == expected


def test_normalize_library_type_base_and_expand():
    assert normalize_detail_to_part({"libraryType": "base"})["library_type"] == "Basic"
    assert normalize_detail_to_part({"libraryType": "expand"})["library_type"] == "Extended"


# ---------------------------------------------------------------------------
# _load_env_file + has_credentials
# ---------------------------------------------------------------------------


def test_load_env_file_never_overrides_existing(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("JLCPCB_APP_ID=from-file\nJLCPCB_API_KEY=key-from-file\n")

    # APP_ID already set in the environment must survive; the unset one loads.
    monkeypatch.setenv("JLCPCB_APP_ID", "already-set")
    monkeypatch.delenv("JLCPCB_API_KEY", raising=False)

    _load_env_file(env)

    import os

    assert os.environ["JLCPCB_APP_ID"] == "already-set"
    assert os.environ["JLCPCB_API_KEY"] == "key-from-file"


def test_load_env_file_missing_path_is_noop(tmp_path):
    # Should not raise when the file does not exist.
    _load_env_file(tmp_path / "does-not-exist.env")


def test_has_credentials():
    assert _client().has_credentials() is True
    assert JLCPCBClient(app_id="a", access_key="b", secret_key=None).has_credentials() is False
    # Constructing with no args reads env; force all-empty to assert False.
    empty = JLCPCBClient(app_id="", access_key="", secret_key="")
    assert empty.has_credentials() is False


# ---------------------------------------------------------------------------
# get_jlcpcb_part handler: live-first-then-local fallback
# ---------------------------------------------------------------------------


@pytest.fixture()
def interface():
    """A KiCADInterface with __init__ skipped and JLCPCB backends mocked."""
    from kicad_interface import KiCADInterface

    iface = object.__new__(KiCADInterface)
    iface.jlcpcb_client = MagicMock()
    iface.jlcpcb_parts = MagicMock()
    iface.jlcpcb_parts.map_package_to_footprint.return_value = ["R_0805_2012Metric"]
    return iface


def test_handler_live_success(interface):
    interface.jlcpcb_client.has_credentials.return_value = True
    interface.jlcpcb_client.get_part_by_lcsc.return_value = {
        "lcsc": "C25804",
        "package": "0805",
        "manufacturer": "Yageo",
        "source": "live-api",
    }

    result = interface._handle_get_jlcpcb_part({"lcsc_number": "C25804"})

    assert result["success"] is True
    assert result["source"] == "live-api"
    assert result["part"]["lcsc"] == "C25804"
    interface.jlcpcb_parts.get_part_info.assert_not_called()


def test_handler_backfills_manufacturer_from_local(interface):
    interface.jlcpcb_client.has_credentials.return_value = True
    interface.jlcpcb_client.get_part_by_lcsc.return_value = {
        "lcsc": "C25804",
        "package": "0805",
        "manufacturer": "",  # live detail lacks manufacturer
        "source": "live-api",
    }
    interface.jlcpcb_parts.get_part_info.return_value = {"manufacturer": "Yageo"}

    result = interface._handle_get_jlcpcb_part({"lcsc_number": "C25804"})

    assert result["source"] == "live-api"
    assert result["part"]["manufacturer"] == "Yageo"


def test_handler_live_failure_falls_back_to_local(interface):
    interface.jlcpcb_client.has_credentials.return_value = True
    interface.jlcpcb_client.get_part_by_lcsc.side_effect = Exception("network down")
    interface.jlcpcb_parts.get_part_info.return_value = {
        "lcsc": "C25804",
        "package": "0805",
        "manufacturer": "Yageo",
    }

    result = interface._handle_get_jlcpcb_part({"lcsc_number": "C25804"})

    assert result["success"] is True
    assert result["source"] == "local-db"
    assert result["part"]["manufacturer"] == "Yageo"


def test_handler_no_creds_uses_local(interface):
    interface.jlcpcb_client.has_credentials.return_value = False
    interface.jlcpcb_parts.get_part_info.return_value = {
        "lcsc": "C25804",
        "package": "0805",
    }

    result = interface._handle_get_jlcpcb_part({"lcsc_number": "C25804"})

    assert result["success"] is True
    assert result["source"] == "local-db"
    interface.jlcpcb_client.get_part_by_lcsc.assert_not_called()


def test_handler_not_found(interface):
    interface.jlcpcb_client.has_credentials.return_value = False
    interface.jlcpcb_parts.get_part_info.return_value = None

    result = interface._handle_get_jlcpcb_part({"lcsc_number": "C999"})

    assert result["success"] is False
    assert "not found" in result["message"].lower()


def test_handler_missing_param(interface):
    result = interface._handle_get_jlcpcb_part({})
    assert result["success"] is False
    assert "lcsc_number" in result["message"]
