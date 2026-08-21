"""Tests for the Digi-Key V4 client.

No test performs a real request. requests.post is monkeypatched, matching the
pattern in test_jlcpcb_live_api.py, and an autouse fixture clears DIGIKEY_* from
the environment so a developer's real credentials can neither be used nor leak
into an assertion message.

Nothing here was recorded from the live service -- there were no working
credentials when this was written. The fixtures below are hand-built from the
documented V4 field names, and their German-language strings ("Aktiv",
"Obsolet", "Gurtabschnitt") are constructed illustrations of the localization
hazard, not captured responses. Treat them as a statement of what the code
does with such a shape, not as evidence of what Digi-Key returns.
"""

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "python"))
from commands import digikey  # noqa: E402
from commands.digikey import (  # noqa: E402
    DigiKeyClient,
    DigiKeyError,
    digikey_check_library_availability,
    digikey_search_parts,
    digikey_test_connection,
    normalize_product,
    read_symbol_part_numbers,
)

ID = "test-client-id-000"
SECRET = "test-client-secret-99999"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """No real credentials, and no .env on disk, may reach these tests."""
    for name in (
        "DIGIKEY_CLIENT_ID",
        "DIGIKEY_CLIENT_SECRET",
        "DIGIKEY_LOCALE_SITE",
        "DIGIKEY_LOCALE_LANGUAGE",
        "DIGIKEY_LOCALE_CURRENCY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(digikey, "_load_env_file", lambda *a, **k: None)
    # The tool entry points memoize a client per locale, so a client built with
    # one test's credentials must not survive into the next.
    digikey.reset_client_cache()
    yield
    digikey.reset_client_cache()


class FakeResponse:
    """A stand-in response.

    ``raise_json`` exists because the original fake could not express the case
    that matters most: an HTTP 200 whose body is not JSON at all. A real
    ``resp.json()`` raises there, and a fake that always returns a dict makes
    the resulting unredacted traceback invisible to the suite.
    """

    def __init__(self, status_code=200, payload=None, text="", headers=None, raise_json=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or json.dumps(self._payload)
        self.headers = headers or {}
        self._raise_json = raise_json

    def json(self):
        if self._raise_json is not None:
            raise self._raise_json
        return self._payload


def non_json(status_code=200, body="<html>Corporate proxy sign-in required</html>"):
    """A 200 carrying a captive-portal / challenge page instead of JSON."""
    return FakeResponse(
        status_code,
        text=body,
        raise_json=json.JSONDecodeError("Expecting value", body, 0),
    )


PRODUCT = {
    "ManufacturerProductNumber": "GRM155R71H104KE14D",
    "Manufacturer": {"Id": 490, "Name": "Murata Electronics"},
    "Description": {"ProductDescription": "CAP CER 0.1UF 50V X7R 0402"},
    "ProductStatus": {"Id": 0, "Status": "Aktiv"},
    "QuantityAvailable": 36419,
    "UnitPrice": 2.32,
    "Marketplace": False,
    "DatasheetUrl": "https://example.invalid/ds.pdf",
    "ProductVariations": [
        {
            "DigiKeyProductNumber": "490-10700-2-ND",
            "PackageType": {"Name": "Tape & Reel (TR)"},
            "MinimumOrderQuantity": 10000,
            "StandardPricing": [{"BreakQuantity": 10000, "UnitPrice": 0.00545}],
        },
        {
            "DigiKeyProductNumber": "490-10700-1-ND",
            "PackageType": {"Name": "Gurtabschnitt"},
            "MinimumOrderQuantity": 1,
            "StandardPricing": [{"BreakQuantity": 1, "UnitPrice": 0.1}],
        },
    ],
    "Parameters": [{"ParameterText": "Toleranz", "ValueText": "\u00b110%"}],
}

OBSOLETE = {
    "ManufacturerProductNumber": "OLD-PART",
    "Manufacturer": {"Name": "Acme"},
    "Description": {"ProductDescription": "old"},
    "ProductStatus": {"Id": 1, "Status": "Obsolet"},
    "QuantityAvailable": 0,
    "ProductVariations": [{"DigiKeyProductNumber": "OLD-ND", "PackageType": {"Name": "Bulk"}}],
}


def install(monkeypatch, handler):
    """Patch requests.post; handler(url, kwargs) returns a FakeResponse."""
    calls = []

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return handler(url, kwargs)

    monkeypatch.setattr(digikey.requests, "post", fake_post)
    return calls


def token_then(payload, status=200, headers=None):
    def handler(url, kwargs):
        if url == digikey.TOKEN_URL:
            return FakeResponse(200, {"access_token": "tok-abc", "expires_in": 1800})
        return FakeResponse(status, payload, headers=headers)

    return handler


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("DIGIKEY_CLIENT_ID", ID)
    monkeypatch.setenv("DIGIKEY_CLIENT_SECRET", SECRET)


def client(**kw):
    kw.setdefault("min_interval", 0)
    return DigiKeyClient(client_id=ID, client_secret=SECRET, **kw)


# --- credentials never leave the process ----------------------------------- #


REPO = Path(__file__).parent.parent


def test_no_source_line_hardcodes_or_logs_a_credential():
    """A source-text guard, not a behavioural one -- named for what it can prove.

    The earlier version of this test asserted a disjunction that any line without
    an ``=`` satisfied automatically, so ``logger.info(self._client_secret)``
    would have sailed through the check that was meant to catch exactly that.
    """
    source = Path(digikey.__file__).read_text(encoding="utf-8")
    assert 'os.environ.get(CLIENT_ID_ENV, "")' in source
    assert 'os.environ.get(CLIENT_SECRET_ENV, "")' in source

    # Every line touching a credential attribute, and what it is allowed to do.
    assignment_sources = ("os.environ", "client_id or", "client_secret or")
    for number, line in enumerate(source.splitlines(), start=1):
        code = line.split("#")[0]
        if "self._client_id" not in code and "self._client_secret" not in code:
            continue
        where = f"{digikey.__file__}:{number}: {line.strip()}"

        # Nothing may route a credential into a log, stdout, or a formatted
        # string. This is the assertion the old disjunction could not make.
        for forbidden in ("logger.", "print(", "warnings.", "f'", 'f"'):
            assert forbidden not in code, where

        # An assignment must take its value from the environment or a keyword
        # argument, never from a literal in the file.
        if "=" in code and "==" not in code and "self._client" in code.split("=", 1)[0]:
            assert any(source_of in code for source_of in assignment_sources), where


def test_dotenv_is_gitignored():
    """A .env is the documented place to put the keys, so it must never be tracked."""
    ignored = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in [line.strip() for line in ignored]


def test_the_env_template_carries_names_without_values():
    """Placeholder-only, including on commented-out lines.

    The comment marker is stripped first: filtering on a bare ``startswith``
    skipped ``# DIGIKEY_CLIENT_SECRET=<real key>``, which is exactly how a real
    key gets committed -- someone comments their working line out instead of
    deleting it.
    """
    template = (REPO / ".env.example").read_text(encoding="utf-8")
    assert "DIGIKEY_CLIENT_ID=" in template
    assert "DIGIKEY_CLIENT_SECRET=" in template
    for raw in template.splitlines():
        line = raw.lstrip().lstrip("#").strip()
        if line.startswith("DIGIKEY_") and "=" in line:
            value = line.split("=", 1)[1].strip()
            assert value in (
                "",
                "your_client_id_here",
                "your_client_secret_here",
                "US",
                "en",
                "USD",
            ), raw


def test_tools_do_not_accept_credentials_as_parameters(monkeypatch):
    """A key passed in a tool call would end up in the transcript and the logs."""
    install(monkeypatch, token_then({"Products": [PRODUCT]}))
    r = digikey_search_parts(
        {"keywords": "x", "clientId": ID, "clientSecret": SECRET, "apiKey": SECRET}
    )
    assert not r["success"]
    assert "not configured" in r["message"]


def test_a_credential_shaped_argument_is_ignored_and_reported(monkeypatch, configured):
    """Ignored is not the same as rejected, and the caller has to be told which.

    Nothing declares these arguments, so zod drops them before the Python side
    ever sees them and a caller who passes one gets a plain success. The value is
    in the conversation by then, so the response has to say so; staying silent
    is what makes 'rejected' a false description of the behaviour.
    """
    install(monkeypatch, token_then({"Products": [PRODUCT]}))
    r = digikey_search_parts({"keywords": "x", "clientSecret": SECRET, "apiKey": SECRET})

    assert r["success"], "the call must still work -- the argument is dropped, not fatal"
    warning = " ".join(r["warnings"])
    assert "clientSecret" in warning and "apiKey" in warning
    assert "rotated" in warning
    # The name is echoed so the caller knows what to rotate; the value never is.
    assert SECRET not in json.dumps(r)


def test_a_legitimate_argument_does_not_trigger_the_credential_warning(monkeypatch, configured):
    install(monkeypatch, token_then({"Products": [PRODUCT]}))
    r = digikey_search_parts({"keywords": "x", "limit": 1, "preferPackaging": "CT"})
    assert "warnings" not in r


def test_the_secret_is_redacted_from_an_error(monkeypatch):
    def handler(url, kwargs):
        if url == digikey.TOKEN_URL:
            return FakeResponse(200, {"access_token": "t", "expires_in": 1800})
        return FakeResponse(500, {}, text=f"failed for {ID} with {SECRET}")

    install(monkeypatch, handler)
    with pytest.raises(DigiKeyError) as e:
        client().search_keyword("x")
    assert SECRET not in str(e.value)
    assert ID not in str(e.value)
    assert "***" in str(e.value)


def test_a_non_json_token_body_becomes_a_redacted_error(monkeypatch):
    """A 200 that is not JSON must not escape as a raw JSONDecodeError.

    JSONDecodeError is neither a RequestException nor a DigiKeyError, so it used
    to travel past every redaction point in this module and land in the
    dispatcher's catch-all in kicad_interface.py, which returns str(e) plus a
    full traceback in errorDetails.
    """
    calls = install(monkeypatch, lambda url, kwargs: non_json())
    with pytest.raises(DigiKeyError) as e:
        client().search_keyword("x")
    assert "non-JSON" in str(e.value)
    assert "200" in str(e.value)
    assert "Corporate proxy" in str(e.value)
    assert calls[0]["url"] == digikey.TOKEN_URL


def test_a_non_json_search_body_becomes_a_redacted_error(monkeypatch):
    def handler(url, kwargs):
        if url == digikey.TOKEN_URL:
            return FakeResponse(200, {"access_token": "tok-abcdef", "expires_in": 1800})
        return non_json(body=f"<html>proxy rejected {SECRET}</html>")

    install(monkeypatch, handler)
    with pytest.raises(DigiKeyError) as e:
        client().search_keyword("x")
    assert "non-JSON" in str(e.value)
    assert SECRET not in str(e.value)
    assert "***" in str(e.value)


def test_a_non_json_body_does_not_escape_the_tool(monkeypatch, configured):
    """The tool must return a message, not raise into the dispatcher catch-all."""

    def handler(url, kwargs):
        if url == digikey.TOKEN_URL:
            return FakeResponse(200, {"access_token": "tok-abcdef", "expires_in": 1800})
        return non_json()

    install(monkeypatch, handler)
    r = digikey_search_parts({"keywords": "x"})
    assert not r["success"]
    assert "non-JSON" in r["message"]
    assert "Traceback" not in json.dumps(r)


def test_a_json_array_body_is_an_error_not_a_typeerror(monkeypatch):
    def handler(url, kwargs):
        if url == digikey.TOKEN_URL:
            return FakeResponse(200, {"access_token": "tok-abcdef", "expires_in": 1800})
        return FakeResponse(200, ["not", "an", "object"])

    install(monkeypatch, handler)
    with pytest.raises(DigiKeyError) as e:
        client().search_keyword("x")
    assert "not an object" in str(e.value)


def test_the_bearer_token_is_redacted_too(monkeypatch):
    """Belt and braces: no path formats the token today, so keep it that way."""
    token = "tok-secret-value-1234"

    def handler(url, kwargs):
        if url == digikey.TOKEN_URL:
            return FakeResponse(200, {"access_token": token, "expires_in": 1800})
        return FakeResponse(500, {}, text=f"upstream logged bearer {token}")

    install(monkeypatch, handler)
    with pytest.raises(DigiKeyError) as e:
        client().search_keyword("x")
    assert token not in str(e.value)


def test_a_credential_too_short_to_redact_is_never_sent(monkeypatch):
    """The len() >= 4 floor in _redact is safe only because of this refusal.

    Blanket string replacement of a one- or two-character credential would
    scribble over the whole message, so instead of redacting it the module
    refuses to build a request with it.
    """
    calls = install(monkeypatch, token_then({"Products": []}))
    with pytest.raises(DigiKeyError) as e:
        DigiKeyClient(client_id=ID, client_secret="xy", min_interval=0).search_keyword("x")
    assert "DIGIKEY_CLIENT_SECRET" in str(e.value)
    assert "shorter than" in str(e.value)
    assert calls == [], "a credential that cannot be redacted must not reach the network"


def test_the_secret_is_redacted_from_a_transport_error(monkeypatch):
    def handler(url, kwargs):
        raise digikey.requests.exceptions.ConnectionError(f"proxy rejected {SECRET}")

    install(monkeypatch, handler)
    with pytest.raises(DigiKeyError) as e:
        client().search_keyword("x")
    assert SECRET not in str(e.value)


def test_the_secret_is_not_in_a_successful_response(monkeypatch, configured):
    install(monkeypatch, token_then({"Products": [PRODUCT]}))
    blob = json.dumps(digikey_search_parts({"keywords": "cap", "limit": 1}))
    assert SECRET not in blob
    assert ID not in blob


def test_missing_credentials_names_the_variables_and_stops(monkeypatch):
    calls = install(monkeypatch, token_then({"Products": []}))
    r = digikey_search_parts({"keywords": "cap"})
    assert not r["success"]
    assert r["requiredEnvironmentVariables"] == ["DIGIKEY_CLIENT_ID", "DIGIKEY_CLIENT_SECRET"]
    assert calls == []


def test_an_env_file_never_overrides_an_exported_variable(tmp_path, monkeypatch):
    monkeypatch.setattr(digikey, "_load_env_file", digikey._load_env_file)
    monkeypatch.setenv("DIGIKEY_CLIENT_ID", "from-environment")
    env = tmp_path / ".env"
    env.write_text("DIGIKEY_CLIENT_ID=from-file\n", encoding="utf-8")
    digikey._load_env_file(env)
    import os

    assert os.environ["DIGIKEY_CLIENT_ID"] == "from-environment"


# --- the three things the API does not tell you ---------------------------- #


def test_locale_headers_are_always_sent(monkeypatch):
    """Without them every search returns 404, which reads like a wrong URL."""
    calls = install(monkeypatch, token_then({"Products": []}))
    client().search_keyword("x")
    headers = calls[-1]["headers"]
    assert headers["X-DIGIKEY-Locale-Site"] == "US"
    assert headers["X-DIGIKEY-Locale-Language"] == "en"
    assert headers["X-DIGIKEY-Locale-Currency"] == "USD"


def test_locale_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("DIGIKEY_LOCALE_SITE", "DE")
    monkeypatch.setenv("DIGIKEY_LOCALE_LANGUAGE", "de")
    monkeypatch.setenv("DIGIKEY_LOCALE_CURRENCY", "EUR")
    calls = install(monkeypatch, token_then({"Products": []}))
    DigiKeyClient(client_id=ID, client_secret=SECRET, min_interval=0).search_keyword("x")
    assert calls[-1]["headers"]["X-DIGIKEY-Locale-Currency"] == "EUR"


def test_a_404_is_explained_as_a_locale_problem(monkeypatch):
    install(monkeypatch, token_then({}, status=404))
    with pytest.raises(DigiKeyError) as e:
        client().search_keyword("x")
    assert "locale headers" in str(e.value)


def test_the_part_number_comes_from_a_variation_not_the_product():
    """DigiKeyProductNumber is per packaging; there is none on the product."""
    assert "DigiKeyProductNumber" not in PRODUCT
    assert normalize_product(PRODUCT)["digikeyPartNumber"] == "490-10700-2-ND"


def test_cut_tape_is_selected_by_its_localized_name():
    """Matching only the English 'Cut Tape' would miss a localized packaging name.

    The fixture uses 'Gurtabschnitt' to stand in for any non-English name; it is
    constructed, not a captured response.
    """
    assert normalize_product(PRODUCT, "CT")["digikeyPartNumber"] == "490-10700-1-ND"
    assert normalize_product(PRODUCT, "TR")["digikeyPartNumber"] == "490-10700-2-ND"


def test_every_variation_is_still_reported():
    assert [v["digikeyPartNumber"] for v in normalize_product(PRODUCT)["variations"]] == [
        "490-10700-2-ND",
        "490-10700-1-ND",
    ]


def test_lifecycle_is_decided_by_id_not_by_the_localized_string():
    """Comparing the status string to 'Active' fails for any non-English locale.

    The fixture's 'Aktiv' stands in for that; the id is what the code reads.
    ACTIVE_STATUS_ID is an assumption -- see the provenance note in the module
    docstring -- so this asserts that the id decides, not that 0 is right.
    """
    assert normalize_product(PRODUCT)["active"] is True
    assert normalize_product(PRODUCT)["status"] == "Aktiv"
    assert normalize_product(OBSOLETE)["active"] is False


def test_a_product_with_no_orderable_variation_is_not_called_available():
    """digikeyPartNumber lives on ProductVariations, and there may be none.

    Active plus stock plus no orderable number used to classify as 'available',
    which excluded the row from needsAttention precisely when a human has to go
    and work out what to put on the order.
    """
    ghost = {
        "ManufacturerProductNumber": "GHOST-1",
        "Manufacturer": {"Name": "Acme"},
        "ProductStatus": {"Id": 0, "Status": "Aktiv"},
        "QuantityAvailable": 5000,
        "ProductVariations": [],
    }
    normalized = normalize_product(ghost)
    assert normalized["digikeyPartNumber"] == ""
    assert normalized["active"] is True
    assert digikey._classify(normalized) == "not_orderable"


def test_normalize_product_survives_a_nested_field_that_is_not_an_object():
    """A response is not a contract, and AttributeError here reads as a code bug."""
    weird = {
        "ManufacturerProductNumber": "X",
        "Manufacturer": "Acme",
        "Description": "just a string",
        "ProductStatus": None,
        "ProductVariations": [{"DigiKeyProductNumber": "X-ND", "PackageType": "Bulk"}, "junk"],
        "Parameters": ["junk"],
    }
    normalized = normalize_product(weird)
    assert normalized["manufacturer"] == ""
    assert normalized["description"] == ""
    assert normalized["digikeyPartNumber"] == "X-ND"
    assert normalized["packaging"] == ""
    assert normalized["parameters"] == []


# --- token handling -------------------------------------------------------- #


def test_the_token_is_reused_across_requests(monkeypatch):
    """Class-level reuse. The tool-level equivalent is asserted separately below.

    This test constructs one client by hand, so on its own it proves nothing
    about the shipped behaviour: the tools used to build a fresh client per call,
    and this passed the whole time.
    """
    calls = install(monkeypatch, token_then({"Products": []}))
    c = client()
    c.search_keyword("a")
    c.search_keyword("b")
    assert sum(1 for x in calls if x["url"] == digikey.TOKEN_URL) == 1


def test_two_tool_calls_share_one_token(monkeypatch, configured):
    """Through the TOOL entry point, which is where the cost is actually paid.

    A client per call bought a token per call, doubling the request count against
    the token endpoint -- the tightest rate limit in the API -- for tokens that
    are valid for thirty minutes.
    """
    calls = install(monkeypatch, token_then({"Products": []}))
    digikey_search_parts({"keywords": "a"})
    digikey_search_parts({"keywords": "b"})
    assert sum(1 for x in calls if x["url"] == digikey.TOKEN_URL) == 1


def test_the_env_file_is_not_re_read_on_every_tool_call(monkeypatch, configured):
    reads = []
    monkeypatch.setattr(digikey, "_load_env_file", lambda *a, **k: reads.append(1))
    install(monkeypatch, token_then({"Products": []}))
    digikey_search_parts({"keywords": "a"})
    digikey_search_parts({"keywords": "b"})
    digikey_test_connection({})
    assert len(reads) == 1


def test_a_different_locale_gets_its_own_client(monkeypatch, configured):
    """The cache is keyed on the resolved locale, not shared across all of them."""
    calls = install(monkeypatch, token_then({"Products": []}))
    digikey_search_parts({"keywords": "a"})
    digikey_search_parts({"keywords": "b", "locale": {"site": "DE", "currency": "EUR"}})
    sites = [
        x["headers"]["X-DIGIKEY-Locale-Site"]
        for x in calls
        if x["url"] == digikey.KEYWORD_SEARCH_URL
    ]
    assert sites == ["US", "DE"]


def test_a_corrected_credential_takes_effect_without_a_restart(monkeypatch):
    """A cached client must not outlive the credentials it was built with."""
    monkeypatch.setenv("DIGIKEY_CLIENT_ID", ID)
    monkeypatch.setenv("DIGIKEY_CLIENT_SECRET", "wrong-secret-value")
    calls = install(monkeypatch, token_then({"Products": []}))
    digikey_search_parts({"keywords": "a"})

    monkeypatch.setenv("DIGIKEY_CLIENT_SECRET", SECRET)
    digikey_search_parts({"keywords": "b"})
    secrets = [x["data"]["client_secret"] for x in calls if x["url"] == digikey.TOKEN_URL]
    assert secrets == ["wrong-secret-value", SECRET]


def test_an_unconfigured_client_is_not_cached(monkeypatch):
    """Otherwise a .env written after the first failed call would never be read."""
    install(monkeypatch, token_then({"Products": []}))
    assert not digikey_search_parts({"keywords": "a"})["success"]

    monkeypatch.setenv("DIGIKEY_CLIENT_ID", ID)
    monkeypatch.setenv("DIGIKEY_CLIENT_SECRET", SECRET)
    assert digikey_search_parts({"keywords": "a"})["success"]


def test_an_expired_token_is_refreshed(monkeypatch):
    calls = install(monkeypatch, token_then({"Products": []}))
    c = client()
    c.search_keyword("a")
    c._token_expires_at = 0
    c.search_keyword("b")
    assert sum(1 for x in calls if x["url"] == digikey.TOKEN_URL) == 2


def test_a_401_mid_flight_refreshes_once_and_retries(monkeypatch):
    state = {"searches": 0}

    def handler(url, kwargs):
        if url == digikey.TOKEN_URL:
            return FakeResponse(200, {"access_token": "t", "expires_in": 1800})
        state["searches"] += 1
        if state["searches"] == 1:
            return FakeResponse(401, {})
        return FakeResponse(200, {"Products": [PRODUCT]})

    calls = install(monkeypatch, handler)
    assert client().search_keyword("x")["Products"]
    assert sum(1 for x in calls if x["url"] == digikey.TOKEN_URL) == 2


def test_a_persistent_401_is_not_retried_forever(monkeypatch):
    install(monkeypatch, token_then({}, status=401))
    with pytest.raises(DigiKeyError):
        client().search_keyword("x")


def test_a_429_waits_and_retries(monkeypatch):
    slept = []
    monkeypatch.setattr(digikey.time, "sleep", lambda s: slept.append(s))
    state = {"n": 0}

    def handler(url, kwargs):
        if url == digikey.TOKEN_URL:
            return FakeResponse(200, {"access_token": "t", "expires_in": 1800})
        state["n"] += 1
        if state["n"] == 1:
            return FakeResponse(429, {}, headers={"Retry-After": "2"})
        return FakeResponse(200, {"Products": []})

    install(monkeypatch, handler)
    client().search_keyword("x")
    assert 2 in slept


def retry_after(monkeypatch, header_value):
    """Run one 429-then-200 exchange and report what time.sleep was asked for."""
    slept = []
    monkeypatch.setattr(digikey.time, "sleep", lambda s: slept.append(s))
    state = {"n": 0}

    def handler(url, kwargs):
        if url == digikey.TOKEN_URL:
            return FakeResponse(200, {"access_token": "tok-abcdef", "expires_in": 1800})
        state["n"] += 1
        if state["n"] == 1:
            headers = {} if header_value is None else {"Retry-After": header_value}
            return FakeResponse(429, {}, headers=headers)
        return FakeResponse(200, {"Products": []})

    install(monkeypatch, handler)
    client().search_keyword("x")
    return slept


def test_an_http_date_retry_after_does_not_crash(monkeypatch):
    """RFC 7231 allows an HTTP-date, and float() on one raises ValueError.

    A ValueError here is neither RequestException nor DigiKeyError, so it took
    the same unredacted-traceback route out of the module as a non-JSON body.
    """
    slept = retry_after(monkeypatch, "Wed, 21 Oct 2026 07:28:00 GMT")
    assert all(s <= digikey.RETRY_AFTER_CAP_SECONDS for s in slept)


def test_a_daily_quota_retry_after_is_capped(monkeypatch):
    """86400 is a legal answer to a daily quota, and the worker is single-threaded.

    Sleeping for it literally does not just stall Digi-Key: every other tool in
    the server queues behind the same Python process for a day.
    """
    slept = retry_after(monkeypatch, "86400")
    assert max(slept) == digikey.RETRY_AFTER_CAP_SECONDS


@pytest.mark.parametrize(
    "header",
    [None, "", "  ", "soon", "nan", "inf", "-10", "Wed, 21 Oct 2026 07:28:00 GMT", "not-a-date"],
)
def test_a_hostile_retry_after_falls_back_to_a_sane_delay(monkeypatch, header):
    slept = retry_after(monkeypatch, header)
    assert slept, "the 429 path must still wait before retrying"
    for value in slept:
        assert isinstance(value, float)
        assert 0 <= value <= digikey.RETRY_AFTER_CAP_SECONDS


def test_retry_after_seconds_honours_a_plausible_delay():
    assert digikey._retry_after_seconds("7") == 7.0
    assert digikey._retry_after_seconds(None) == digikey.DEFAULT_RETRY_AFTER_SECONDS
    assert digikey._retry_after_seconds("86400") == digikey.RETRY_AFTER_CAP_SECONDS


def test_bad_credentials_say_so_rather_than_reporting_a_network_error(monkeypatch):
    def handler(url, kwargs):
        return FakeResponse(401, {"error": "invalid_client"})

    install(monkeypatch, handler)
    with pytest.raises(DigiKeyError) as e:
        client().search_keyword("x")
    assert "rejected the credentials" in str(e.value)
    assert "Production app" in str(e.value)


# --- search tool ----------------------------------------------------------- #


def test_search_returns_normalized_products(monkeypatch, configured):
    install(monkeypatch, token_then({"Products": [PRODUCT], "ExactMatches": 1}))
    r = digikey_search_parts({"keywords": "GRM155R71H104KE14D"})
    assert r["success"]
    assert r["products"][0]["manufacturer"] == "Murata Electronics"
    assert r["products"][0]["quantityAvailable"] == 36419
    assert r["exactMatches"] == 1


def test_search_with_no_results_is_a_success_with_an_empty_list(monkeypatch, configured):
    install(monkeypatch, token_then({"Products": []}))
    r = digikey_search_parts({"keywords": "nonexistent"})
    assert r["success"]
    assert r["products"] == []
    assert "no match" in r["message"]


def test_search_requires_keywords(configured):
    assert not digikey_search_parts({})["success"]


def test_the_limit_is_clamped(monkeypatch, configured):
    calls = install(monkeypatch, token_then({"Products": []}))
    digikey_search_parts({"keywords": "x", "limit": 5000})
    assert calls[-1]["json"]["Limit"] == 50


def test_connection_test_reports_the_locale(monkeypatch, configured):
    install(monkeypatch, token_then({"Products": [PRODUCT]}))
    r = digikey_test_connection({})
    assert r["success"]
    assert r["locale"]["site"] == "US"


def test_connection_test_without_credentials(monkeypatch):
    r = digikey_test_connection({})
    assert not r["success"]
    assert "DIGIKEY_CLIENT_ID" in r["requiredEnvironmentVariables"]


# --- library sweep --------------------------------------------------------- #


def symbol(name, props):
    out = f'\t(symbol "{name}"\n'
    for k, v in props.items():
        out += f'\t\t(property "{k}" "{v}"\n\t\t\t(at 0 0 0)\n\t\t)\n'
    return out + "\t)\n"


LIB = (
    "(kicad_symbol_lib\n\t(version 20241209)\n"
    + symbol(
        "C_100nF_0402",
        {
            "Value": "100nF",
            "MANUFACTURER PART NUMBER": "GRM155R71H104KE14D",
            "SUPPLIER PART NUMBER 1": "490-10700-1-ND",
        },
    )
    + symbol("OLD_PART", {"Value": "x", "MPN": "OLD-PART"})
    + symbol("NO_NUMBERS", {"Value": "y"})
    + ")\n"
)


@pytest.fixture
def lib(tmp_path):
    path = tmp_path / "L.kicad_sym"
    path.write_text(LIB, encoding="utf-8")
    return path


def test_part_numbers_are_read_under_any_property_spelling():
    rows = {s["name"]: s for s in read_symbol_part_numbers(LIB)}
    assert rows["C_100nF_0402"]["mpn"] == "GRM155R71H104KE14D"
    assert rows["C_100nF_0402"]["supplierPartNumber"] == "490-10700-1-ND"
    assert rows["OLD_PART"]["mpn"] == "OLD-PART"
    assert rows["NO_NUMBERS"]["mpn"] == ""


def test_the_sweep_classifies_each_symbol(monkeypatch, configured, lib):
    def handler(url, kwargs):
        if url == digikey.TOKEN_URL:
            return FakeResponse(200, {"access_token": "t", "expires_in": 1800})
        keyword = kwargs["json"]["Keywords"]
        if keyword == "OLD-PART":
            return FakeResponse(200, {"Products": [OBSOLETE]})
        if keyword in ("490-10700-1-ND", "GRM155R71H104KE14D"):
            return FakeResponse(200, {"Products": [PRODUCT]})
        return FakeResponse(200, {"Products": []})

    install(monkeypatch, handler)
    r = digikey_check_library_availability({"libraryPath": str(lib)})
    states = {row["symbol"]: row["state"] for row in r["results"]}
    assert states == {
        "C_100nF_0402": "available",
        "OLD_PART": "inactive",
        "NO_NUMBERS": "no_part_number",
    }
    assert sorted(r["needsAttention"]) == ["NO_NUMBERS", "OLD_PART"]


def test_the_sweep_falls_back_to_the_mpn(monkeypatch, configured, lib):
    """Old Digi-Key numbers get retired; the MPN usually still resolves."""
    seen = []

    def handler(url, kwargs):
        if url == digikey.TOKEN_URL:
            return FakeResponse(200, {"access_token": "t", "expires_in": 1800})
        keyword = kwargs["json"]["Keywords"]
        seen.append(keyword)
        if keyword == "GRM155R71H104KE14D":
            return FakeResponse(200, {"Products": [PRODUCT]})
        return FakeResponse(200, {"Products": []})

    install(monkeypatch, handler)
    r = digikey_check_library_availability({"libraryPath": str(lib), "symbols": ["C_100nF_0402"]})
    assert seen == ["490-10700-1-ND", "GRM155R71H104KE14D"]
    assert r["results"][0]["searchedBy"] == "mpn"
    assert r["results"][0]["state"] == "available"


def test_search_order_can_start_with_the_mpn(monkeypatch, configured, lib):
    seen = []

    def handler(url, kwargs):
        if url == digikey.TOKEN_URL:
            return FakeResponse(200, {"access_token": "t", "expires_in": 1800})
        seen.append(kwargs["json"]["Keywords"])
        return FakeResponse(200, {"Products": [PRODUCT]})

    install(monkeypatch, handler)
    digikey_check_library_availability(
        {"libraryPath": str(lib), "symbols": ["C_100nF_0402"], "searchByMpnFirst": True}
    )
    assert seen == ["GRM155R71H104KE14D"]


def test_the_sweep_is_capped(monkeypatch, configured, lib):
    install(monkeypatch, token_then({"Products": [PRODUCT]}))
    r = digikey_check_library_availability({"libraryPath": str(lib), "maxSymbols": 1})
    assert r["truncated"] is True
    assert r["checked"] == 1
    assert "maxSymbols=1" in r["message"]


def test_a_transient_failure_does_not_discard_the_rest_of_the_sweep(monkeypatch, configured, lib):
    """One 500 used to abandon every symbol after it, paid for and unreported.

    The sweep costs one or two rate-limited requests per symbol, so throwing
    away the successful lookups means buying all of them again -- and a single
    500, a DNS blip or a second consecutive 429 is likely in a burst against an
    API this branch itself describes as aggressively rate limited.
    """
    state = {"n": 0}

    def handler(url, kwargs):
        if url == digikey.TOKEN_URL:
            return FakeResponse(200, {"access_token": "tok-abcdef", "expires_in": 1800})
        state["n"] += 1
        if state["n"] == 1:
            return FakeResponse(500, {}, text="upstream exploded")
        return FakeResponse(200, {"Products": [PRODUCT]})

    install(monkeypatch, handler)
    r = digikey_check_library_availability({"libraryPath": str(lib)})

    rows = {row["symbol"]: row for row in r["results"]}
    assert r["checked"] == 3, "every symbol is still visited"
    assert rows["C_100nF_0402"]["state"] == "error"
    assert "500" in rows["C_100nF_0402"]["message"]
    assert rows["OLD_PART"]["state"] == "available", "the symbols after the failure still ran"
    assert r["errors"] == 1
    assert r["counts"]["error"] == 1
    assert r["success"], "a partial sweep is still a useful sweep"
    assert "C_100nF_0402" in r["needsAttention"]
    assert r["aborted"] is None


def test_a_sweep_that_fails_on_every_symbol_is_not_a_success(monkeypatch, configured, lib):
    install(monkeypatch, token_then({}, status=500))
    r = digikey_check_library_availability({"libraryPath": str(lib), "symbols": ["OLD_PART"]})
    assert not r["success"]
    assert r["errors"] == 1


def test_the_sweep_gives_up_after_repeated_failures(monkeypatch, configured, tmp_path):
    """A revoked key fails identically for every symbol; do not buy 100 of those."""
    many = "(kicad_symbol_lib\n\t(version 20241209)\n" + "".join(
        symbol(f"S{i}", {"MPN": f"MPN-{i}"}) for i in range(12)
    )
    path = tmp_path / "many.kicad_sym"
    path.write_text(many + ")\n", encoding="utf-8")

    searches = []

    def handler(url, kwargs):
        if url == digikey.TOKEN_URL:
            return FakeResponse(200, {"access_token": "tok-abcdef", "expires_in": 1800})
        searches.append(kwargs["json"]["Keywords"])
        return FakeResponse(500, {}, text="upstream exploded")

    install(monkeypatch, handler)
    r = digikey_check_library_availability({"libraryPath": str(path)})

    limit = digikey.MAX_CONSECUTIVE_SWEEP_ERRORS
    assert len(searches) == limit, "the sweep must stop, not grind through all twelve"
    assert r["checked"] == limit
    assert r["aborted"] and "consecutive failures" in r["aborted"]
    assert "7 symbol(s) not checked" in r["aborted"]
    assert not r["success"]


def test_the_consecutive_failure_counter_resets_on_a_success(monkeypatch, configured, tmp_path):
    """Scattered failures across a long library must not add up to an abort."""
    many = "(kicad_symbol_lib\n\t(version 20241209)\n" + "".join(
        symbol(f"S{i}", {"MPN": f"MPN-{i}"}) for i in range(12)
    )
    path = tmp_path / "many.kicad_sym"
    path.write_text(many + ")\n", encoding="utf-8")

    def handler(url, kwargs):
        if url == digikey.TOKEN_URL:
            return FakeResponse(200, {"access_token": "tok-abcdef", "expires_in": 1800})
        index = int(kwargs["json"]["Keywords"].split("-")[1])
        if index % 2:
            return FakeResponse(500, {}, text="upstream exploded")
        return FakeResponse(200, {"Products": [PRODUCT]})

    install(monkeypatch, handler)
    r = digikey_check_library_availability({"libraryPath": str(path)})
    assert r["checked"] == 12
    assert r["errors"] == 6
    assert r["aborted"] is None
    assert r["success"]


def test_a_symbol_with_no_orderable_number_reaches_needs_attention(monkeypatch, configured, lib):
    ghost = {
        "ManufacturerProductNumber": "GRM155R71H104KE14D",
        "Manufacturer": {"Name": "Murata Electronics"},
        "ProductStatus": {"Id": 0, "Status": "Aktiv"},
        "QuantityAvailable": 5000,
        "ProductVariations": [],
    }
    install(monkeypatch, token_then({"Products": [ghost]}))
    r = digikey_check_library_availability({"libraryPath": str(lib), "symbols": ["C_100nF_0402"]})
    assert r["results"][0]["state"] == "not_orderable"
    assert r["results"][0]["digikeyPartNumber"] == ""
    assert r["needsAttention"] == ["C_100nF_0402"]


def test_the_sweep_default_is_small_enough_to_finish(monkeypatch, configured, lib):
    """The default has to fit the Node-side timeout, not just be a round number.

    DigiKeyClient throttles itself to min_interval between requests, so 100
    symbols cost 25 s of self-imposed delay before any network latency -- past
    DEFAULT_COMMAND_TIMEOUT_MS on its own, and the sweep can need two requests
    per symbol. src/command-timeout.ts grants the extended allowance; this keeps
    the default well inside it either way.
    """
    assert digikey.DEFAULT_MAX_SYMBOLS == 25

    install(monkeypatch, token_then({"Products": [PRODUCT]}))
    r = digikey_check_library_availability({"libraryPath": str(lib)})
    assert "maxSymbols" not in r["message"], "three symbols is under the default"

    throttle = DigiKeyClient(client_id=ID, client_secret=SECRET).min_interval
    worst_case = digikey.DEFAULT_MAX_SYMBOLS * 2 * throttle
    assert worst_case < 30.0, f"the default self-throttles for {worst_case}s before latency"


def test_the_node_side_grants_the_sweep_an_extended_timeout():
    """Without this the 30 s default fires mid-sweep.

    Since #382 the late response is discarded by request id instead of being
    handed to the caller's next tool call, so what a timeout costs is this
    command's whole result set -- every lookup in it already charged against the
    caller's Digi-Key rate limit.
    """
    source = (REPO / "src" / "command-timeout.ts").read_text(encoding="utf-8")
    listed = source.split("LONG_RUNNING_COMMANDS", 1)[1].split("]", 1)[0]
    assert '"digikey_check_library_availability"' in listed


# --- the Python-side schemas ----------------------------------------------- #
#
# tools/list is built from TOOL_SCHEMAS, so a tool absent from it is advertised
# with only a best-effort schema derived from annotations. The three below are
# listed there, and these tests keep that listing honest against the zod
# definitions in src/tools/digikey-api.ts, which are the ones the MCP client
# actually validates against.

DIGIKEY_TOOL_NAMES = (
    "digikey_test_connection",
    "digikey_search_parts",
    "digikey_check_library_availability",
)


def _ts_tool_blocks():
    """Split digikey-api.ts into one text block per server.tool() call.

    Slicing from the first call is what keeps the shared localeSchema
    definition -- whose own site/language/currency fields would otherwise be
    read as tool parameters -- out of every block.
    """
    source = (REPO / "src" / "tools" / "digikey-api.ts").read_text(encoding="utf-8")
    blocks = {}
    for chunk in source.split("server.tool(")[1:]:
        for name in DIGIKEY_TOOL_NAMES:
            if f'"{name}"' in chunk:
                blocks[name] = chunk
    return blocks


@pytest.mark.parametrize("name", DIGIKEY_TOOL_NAMES)
def test_the_python_schema_is_registered(name):
    from schemas.tool_schemas import TOOL_SCHEMAS

    assert name in TOOL_SCHEMAS
    entry = TOOL_SCHEMAS[name]
    assert entry.get("title")
    assert entry.get("description")
    assert entry["inputSchema"]["type"] == "object"


@pytest.mark.parametrize("name", DIGIKEY_TOOL_NAMES)
def test_the_python_schema_declares_the_same_parameters_as_the_zod_schema(name):
    """A parameter in one and not the other is a tool that describes itself
    differently depending on which side of the bridge is asked."""
    from schemas.tool_schemas import TOOL_SCHEMAS

    block = _ts_tool_blocks()[name]
    # A parameter is a `field: z...` or `field: localeSchema` in the shape
    # object. The `z` is matched as a bare word rather than as `z.` because
    # prettier breaks the longer builders onto the next line, and the handler's
    # own TypeScript annotations (`keywords: string`, `locale?: {...}`) match
    # neither form.
    declared = set(re.findall(r"(\w+):\s*(?:z\b|localeSchema\b)", block))
    assert declared, f"found no zod parameters for {name}"
    assert set(TOOL_SCHEMAS[name]["inputSchema"]["properties"]) == declared


def test_the_required_parameters_are_the_ones_without_a_default():
    from schemas.tool_schemas import TOOL_SCHEMAS

    assert "required" not in TOOL_SCHEMAS["digikey_test_connection"]["inputSchema"]
    assert TOOL_SCHEMAS["digikey_search_parts"]["inputSchema"]["required"] == ["keywords"]
    sweep = TOOL_SCHEMAS["digikey_check_library_availability"]["inputSchema"]
    assert sweep["required"] == ["libraryPath"]
    assert sweep["properties"]["maxSymbols"]["default"] == digikey.DEFAULT_MAX_SYMBOLS


def test_no_python_schema_offers_a_credential_shaped_parameter():
    """The central security claim, asserted on this side of the bridge too.

    A credential belongs in the environment: an argument is in the caller's
    transcript, in the MCP log, and in anything that replays the call. The
    vitest in tests-ts/digikey-schemas.test.ts makes the same assertion about
    the zod schemas.
    """
    from schemas.tool_schemas import TOOL_SCHEMAS

    banned = ("secret", "token", "credential", "password", "apikey", "clientid", "client_id")
    for name in DIGIKEY_TOOL_NAMES:
        rendered = json.dumps(TOOL_SCHEMAS[name]["inputSchema"]["properties"]).lower()
        for field in TOOL_SCHEMAS[name]["inputSchema"]["properties"]:
            flat = field.lower().replace("_", "")
            assert not any(b.replace("_", "") in flat for b in banned), f"{name}.{field}"
        # The description may name the environment variables; it must not
        # invite them as input.
        assert "pass your" not in rendered


def test_the_sweep_schema_matches_what_the_sweep_actually_does():
    """The schema text is what the model reads when it picks maxSymbols."""
    schema = (REPO / "src" / "tools" / "digikey-api.ts").read_text(encoding="utf-8")
    assert f"default {digikey.DEFAULT_MAX_SYMBOLS}" in schema
    assert "default 100" not in schema
    # The MPN fallback makes it up to 2N + 1, not N.
    assert "One request per symbol" not in schema
    assert "two rate-limited requests per symbol" in schema


@pytest.mark.parametrize("bad", ["lots", None, "", 3.7, {"a": 1}])
def test_a_nonsense_max_symbols_falls_back_instead_of_raising(monkeypatch, configured, lib, bad):
    """The Python dispatcher is reachable directly, past the TypeScript schema."""
    install(monkeypatch, token_then({"Products": [PRODUCT]}))
    r = digikey_check_library_availability({"libraryPath": str(lib), "maxSymbols": bad})
    assert r["success"]


def test_a_negative_max_symbols_does_not_slice_from_the_end(monkeypatch, configured, lib):
    """entries[:-5] reported a truncated sweep of nothing at all."""
    install(monkeypatch, token_then({"Products": [PRODUCT]}))
    r = digikey_check_library_availability({"libraryPath": str(lib), "maxSymbols": -5})
    assert r["checked"] == 1
    assert "maxSymbols=1" in r["message"]


@pytest.mark.parametrize("bad", ["ten", None, {"a": 1}])
def test_a_nonsense_limit_falls_back_instead_of_raising(monkeypatch, configured, bad):
    calls = install(monkeypatch, token_then({"Products": []}))
    assert digikey_search_parts({"keywords": "x", "limit": bad})["success"]
    assert calls[-1]["json"]["Limit"] == 10


def test_the_sweep_needs_credentials_before_reading_the_network(monkeypatch, lib):
    calls = install(monkeypatch, token_then({"Products": []}))
    r = digikey_check_library_availability({"libraryPath": str(lib)})
    assert not r["success"]
    assert calls == []


def test_a_schematic_is_not_a_symbol_library(tmp_path, configured):
    path = tmp_path / "b.kicad_sch"
    path.write_text("(kicad_sch\n)\n", encoding="utf-8")
    r = digikey_check_library_availability({"libraryPath": str(path)})
    assert not r["success"]
    assert "kicad_symbol_lib" in r["message"]


def test_a_missing_library(tmp_path, configured):
    r = digikey_check_library_availability({"libraryPath": str(tmp_path / "no.kicad_sym")})
    assert not r["success"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
