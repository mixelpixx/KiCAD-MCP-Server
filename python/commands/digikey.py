"""Digi-Key Product Information V4 client.

The server had six JLCPCB tools and nothing for Digi-Key, so every stock check,
lifecycle check and replacement hunt happened in one-off scripts outside it.

Credentials are read from the environment only -- ``DIGIKEY_CLIENT_ID`` and
``DIGIKEY_CLIENT_SECRET``, optionally via a gitignored ``.env``. No tool
parameter can supply one, and no credential is written to a file, logged, or
returned in a response: everything leaving this module goes through ``_redact``.
There is no default, no fallback and no bundled key, so a missing credential is
reported as a missing credential rather than silently reaching for someone
else's.

Note the precise claim: a credential-shaped argument is *ignored*, not rejected.
Nothing declares such a parameter, so the schema layer strips it and the value
never reaches this module -- but it has already been written into the caller's
transcript by then, so ``_credential_warning`` names it in the response and says
to rotate it. Calling that "rejected" would imply the key never left the
caller's machine.

Three things this client handles that are easy to get wrong:

* The locale headers are mandatory. Without ``X-DIGIKEY-Locale-Site`` and its
  two companions a search returns **404**, which reads like a wrong URL.
* The Digi-Key part number is not on the product. It lives on each entry of
  ``ProductVariations``, one per packaging option, and the reel and the cut
  tape have different numbers.
* ``ProductStatus.Status`` is localized, so comparing it against ``"Active"``
  misreports every part as soon as the account is not set to English --
  a German-language account returns a German status string.
  ``ProductStatus.Id`` is the stable field; ``ACTIVE_STATUS_ID`` below records
  what this module assumes it means, and how confident that is.

Provenance, so nobody has to guess later: none of this has been exercised
against the live Digi-Key service. There were no working credentials while it
was written -- the token endpoint answers ``401 invalid_client`` -- so every
test drives a mocked ``requests.post``, and the German-language strings in the
fixtures are constructed illustrations of the localization hazard rather than
captured responses.
"""

from __future__ import annotations

import logging
import math
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests
from utils.sexpr_format import iter_child_offsets, match_paren

logger = logging.getLogger("kicad_interface")

TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"
KEYWORD_SEARCH_URL = "https://api.digikey.com/products/v4/search/keyword"

CLIENT_ID_ENV = "DIGIKEY_CLIENT_ID"
CLIENT_SECRET_ENV = "DIGIKEY_CLIENT_SECRET"

# Blanket string replacement is how credentials are kept out of messages, and a
# credential of one or two characters would replace half the alphabet with
# ``***``. Rather than leave short values unredacted, anything shorter than this
# is refused before a request is built -- no real Digi-Key credential is close to
# it, so the only thing rejected is a typo or a truncated paste.
MIN_CREDENTIAL_LENGTH = 4

# Locale defaults. Any valid Digi-Key site works; what matters is that the
# headers are sent at all.
LOCALE_ENV = {
    "site": ("DIGIKEY_LOCALE_SITE", "US"),
    "language": ("DIGIKEY_LOCALE_LANGUAGE", "en"),
    "currency": ("DIGIKEY_LOCALE_CURRENCY", "USD"),
}

# The id this module treats as "active". It has NOT been confirmed against a
# live Digi-Key response -- see the provenance note in the module docstring --
# so treat it as an assumption to check the first time the integration runs
# against the real service. Every other id is reported verbatim rather than
# mapped to a guessed meaning, because the id space is not documented here and
# the accompanying status string is localized.
ACTIVE_STATUS_ID = 0

# The sweep issues one or two rate-limited requests per symbol and throttles
# itself between them, so its default has to be a number that finishes inside
# the Node-side command timeout. src/command-timeout.ts grants the sweep the
# extended allowance; this keeps the default well inside it.
DEFAULT_MAX_SYMBOLS = 25

# One transient error should not discard the symbols already looked up, but a
# revoked key should not grind through the whole library either.
MAX_CONSECUTIVE_SWEEP_ERRORS = 5

# Ceiling on an honoured Retry-After. The Python worker is single-threaded, so
# sleeping here blocks every other tool in the server.
RETRY_AFTER_CAP_SECONDS = 30.0
DEFAULT_RETRY_AFTER_SECONDS = 5.0

# Argument names that look like a credential. They are not in any tool schema,
# so they arrive only from a caller that invented them; the value is discarded,
# but it is in the transcript by then and the caller needs to hear that.
_CREDENTIAL_ARG = re.compile(r"client_?id|client_?secret|secret|api_?key|token|password", re.I)

# Packaging names are localized too: a German account calls cut tape
# "Gurtabschnitt". Matching the English name only would quietly return the reel
# to a caller who asked for cut tape.
PACKAGING_SYNONYMS: Dict[str, Tuple[str, ...]] = {
    "TR": ("tape & reel", "tape and reel", "(tr)"),
    "CT": ("cut tape", "gurtabschnitt", "(ct)"),
    "DKR": ("digi-reel", "digireel"),
}

# Property names that hold a part number, best first, compared after _norm_key.
MPN_KEYS = (
    "MPN",
    "MANUFACTURERPARTNUMBER",
    "MFRPARTNUMBER",
    "MANUFACTURERPARTNO",
    "MP",
    "PARTNUMBER",
)
SUPPLIER_KEYS = (
    "DIGIKEY",
    "DIGIKEYPARTNUMBER",
    "DIGIKEYPN",
    "SUPPLIERPARTNUMBER1",
    "SUPPLIERPARTNUMBER",
)

_HEAD = re.compile(r"\(\s*([A-Za-z_][\w]*)")


class DigiKeyError(Exception):
    """A Digi-Key request failed. The message is already redacted."""


def _load_env_file(env_path: Optional[Path] = None) -> None:
    """Best-effort load of a project-root ``.env`` so DIGIKEY_* creds are picked up.

    Non-destructive: a variable already in the environment always wins, so a
    stale ``.env`` cannot override credentials the operator exported.
    """
    try:
        from dotenv import load_dotenv
    except Exception:  # python-dotenv is a declared dep, but degrade gracefully
        return
    if env_path is None:
        # python/commands/digikey.py -> repo root is three parents up.
        env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)


def _norm_key(name: str) -> str:
    return re.sub(r"[\s_\-.#]+", "", name).upper()


def _as_int(value: Any, default: int) -> int:
    """Coerce a parameter to int, falling back rather than raising.

    The TypeScript schemas type these as numbers, but the Python dispatcher is
    also reachable directly, and ``int("ten")`` there becomes an unredacted
    traceback in the dispatcher's catch-all rather than a usable message.
    """
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _sub(container: Any, key: str) -> Dict[str, Any]:
    """A nested object from a response, or ``{}`` if it is absent or not one.

    V4 nests ``Manufacturer``, ``Description`` and ``PackageType`` as objects,
    but a response is not a contract: a bare string where an object was expected
    otherwise raises ``AttributeError`` well away from the request that caused it.
    """
    if not isinstance(container, dict):
        return {}
    value = container.get(key)
    return value if isinstance(value, dict) else {}


def _header(resp: Any, name: str) -> Optional[str]:
    headers = getattr(resp, "headers", None)
    if not headers:
        return None
    try:
        value = headers.get(name)
    except AttributeError:
        return None
    return None if value is None else str(value)


def _retry_after_seconds(value: Optional[str]) -> float:
    """How long to wait for a 429, defensively parsed and capped.

    RFC 7231 allows either a delay in seconds or an HTTP-date, so ``float()``
    alone raises on a perfectly legal header. A daily-quota response can also
    name 86400 seconds, and the Python worker is single-threaded: honouring that
    literally would wedge every other tool in the server for a day.
    """
    delay: Optional[float] = None
    if value is not None:
        text = str(value).strip()
        try:
            delay = float(text)
        except ValueError:
            try:
                when = parsedate_to_datetime(text)
            except (TypeError, ValueError, OverflowError):
                delay = None
            else:
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
                delay = (when - datetime.now(timezone.utc)).total_seconds()
    if delay is None or not math.isfinite(delay) or delay < 0:
        delay = DEFAULT_RETRY_AFTER_SECONDS
    return min(delay, RETRY_AFTER_CAP_SECONDS)


def _credential_warning(params: Dict[str, Any]) -> Optional[str]:
    """Name credential-shaped arguments so the caller knows to rotate them.

    No tool schema declares these, so the TypeScript layer strips them before
    they ever reach here and a caller who passes one sees a successful call with
    the value quietly discarded. Discarded is not the same as never sent: it is
    in the conversation, and probably in a log. Say so instead of staying silent.
    The name is echoed; the value never is.
    """
    offenders = sorted(key for key in params if _CREDENTIAL_ARG.search(key))
    if not offenders:
        return None
    return (
        "Ignored argument(s) whose names look like credentials: "
        + ", ".join(offenders)
        + f". Digi-Key credentials are read only from {CLIENT_ID_ENV} and "
        f"{CLIENT_SECRET_ENV} in the server environment, so the value was not used -- "
        "but it is now in this conversation and should be treated as compromised "
        "and rotated."
    )


def _with_warning(result: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    warning = _credential_warning(params)
    if warning:
        result.setdefault("warnings", []).append(warning)
    return result


def _read_string(text: str, i: int) -> Tuple[Optional[str], int]:
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    if i >= len(text) or text[i] != '"':
        return None, i
    out: List[str] = []
    i += 1
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            out.append(text[i + 1])
            i += 2
            continue
        if ch == '"':
            return "".join(out), i + 1
        out.append(ch)
        i += 1
    return None, i


def read_symbol_part_numbers(text: str) -> List[Dict[str, str]]:
    """Return ``{name, mpn, supplierPartNumber}`` for each symbol in a .kicad_sym.

    Property naming is inconsistent in any library that has seen more than one
    importer -- the same field turns up as ``MPN``, ``MP``,
    ``MANUFACTURER PART NUMBER`` and ``PART NUMBER`` -- so lookup is done on a
    normalized key rather than an exact name.
    """
    symbols: List[Dict[str, str]] = []
    root = _HEAD.search(text)
    if not root:
        return symbols
    for off in iter_child_offsets(text[root.start() :]):
        off += root.start()
        head = _HEAD.match(text, off)
        if not head or head.group(1) != "symbol":
            continue
        end = match_paren(text, off)
        if end == -1:
            continue
        block = text[off : end + 1]
        name, _ = _read_string(text, head.end())
        if not name:
            continue
        props: Dict[str, str] = {}
        for child in iter_child_offsets(block):
            child_head = _HEAD.match(block, child)
            if not child_head or child_head.group(1) != "property":
                continue
            key, after = _read_string(block, child_head.end())
            value, _ = _read_string(block, after)
            if key:
                props[_norm_key(key)] = (value or "").strip()

        def first(keys: Sequence[str]) -> str:
            for key in keys:
                if props.get(key):
                    return props[key]
            return ""

        symbols.append(
            {
                "name": name,
                "mpn": first(MPN_KEYS),
                "supplierPartNumber": first(SUPPLIER_KEYS),
                "value": props.get("VALUE", ""),
            }
        )
    return symbols


class DigiKeyClient:
    """OAuth2 client-credentials client for Digi-Key Product Information V4."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        locale: Optional[Dict[str, str]] = None,
        min_interval: float = 0.25,
        timeout: int = 30,
    ) -> None:
        _load_env_file()
        # Constructor arguments exist for tests. Nothing in the tool surface
        # passes credentials in, so they cannot arrive from a chat transcript
        # or get written into a saved workflow.
        self._client_id = client_id or os.environ.get(CLIENT_ID_ENV, "")
        self._client_secret = client_secret or os.environ.get(CLIENT_SECRET_ENV, "")
        self.locale = locale or {
            field: os.environ.get(env, default) for field, (env, default) in LOCALE_ENV.items()
        }
        self.min_interval = min_interval
        self.timeout = timeout
        self._token: Optional[str] = None
        self._token_expires_at = 0.0
        self._last_request_at = 0.0
        if not self.has_credentials():
            logger.info(
                "Digi-Key credentials not configured (%s / %s); Digi-Key tools will report "
                "how to set them.",
                CLIENT_ID_ENV,
                CLIENT_SECRET_ENV,
            )

    def has_credentials(self) -> bool:
        return bool(self._client_id and self._client_secret)

    def matches_environment_credentials(self) -> bool:
        """Whether this client still holds what the environment currently says.

        The memoization in ``_client`` uses this so a corrected credential takes
        effect on the next tool call rather than at the next server restart.
        """
        return self._client_id == os.environ.get(CLIENT_ID_ENV, "") and (
            self._client_secret == os.environ.get(CLIENT_SECRET_ENV, "")
        )

    def _redact(self, message: str) -> str:
        """Strip credentials from anything on its way to a log or a response.

        An error body may echo the client id, and a misconfigured secret can end
        up in a URL-encoded error. One choke point is easier to keep honest than
        a rule about which strings are safe to format.

        The bearer token is included as belt-and-braces: no current code path
        formats it into a message, and this makes a future one harmless.

        The length floor does not leave a short credential exposed --
        ``_reject_unusable_credentials`` refuses to send one, so a value too
        short to replace safely never reaches a request or an error message.
        """
        for secret in (self._client_secret, self._client_id, self._token):
            if secret and len(secret) >= MIN_CREDENTIAL_LENGTH:
                message = message.replace(secret, "***")
        return message

    def _reject_unusable_credentials(self) -> None:
        too_short = sorted(
            env
            for env, value in (
                (CLIENT_ID_ENV, self._client_id),
                (CLIENT_SECRET_ENV, self._client_secret),
            )
            if len(value) < MIN_CREDENTIAL_LENGTH
        )
        if too_short:
            raise DigiKeyError(
                f"{' and '.join(too_short)} is shorter than {MIN_CREDENTIAL_LENGTH} "
                "characters, which no Digi-Key credential is -- check for a truncated "
                "paste. The value is not sent, because a credential that short cannot be "
                "reliably stripped from an error message."
            )

    def _json_body(self, resp: Any, what: str) -> Dict[str, Any]:
        """Decode a JSON body, converting a non-JSON one into a redacted error.

        A 200 whose body is not JSON is a normal outcome behind a captive
        portal, a corporate proxy interstitial or a challenge page. Letting the
        decode error propagate would skip redaction entirely and surface an
        unfiltered traceback through the dispatcher's catch-all.
        """
        try:
            payload = resp.json()
        except ValueError as e:
            body = str(getattr(resp, "text", ""))[:200]
            raise DigiKeyError(
                self._redact(
                    f"Digi-Key {what} returned a non-JSON body "
                    f"({getattr(resp, 'status_code', '?')}): {e}. Body starts: {body!r}"
                )
            )
        if not isinstance(payload, dict):
            raise DigiKeyError(
                self._redact(
                    f"Digi-Key {what} returned JSON that is not an object "
                    f"({type(payload).__name__})"
                )
            )
        return payload

    def _sleep_for_rate_limit(self) -> None:
        wait = self.min_interval - (time.time() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.time()

    def _fetch_token(self) -> str:
        if not self.has_credentials():
            raise DigiKeyError(
                f"Digi-Key credentials not configured. Set {CLIENT_ID_ENV} and "
                f"{CLIENT_SECRET_ENV} in the environment or in a gitignored .env at the "
                "repo root. Create them at developer.digikey.com under a Production app "
                "with Product Information V4 enabled."
            )
        self._reject_unusable_credentials()
        self._sleep_for_rate_limit()
        try:
            resp = requests.post(
                TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "client_credentials",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as e:
            raise DigiKeyError(self._redact(f"Could not reach Digi-Key: {e}"))

        if resp.status_code == 401:
            raise DigiKeyError(
                f"Digi-Key rejected the credentials (401). Check {CLIENT_ID_ENV} and "
                f"{CLIENT_SECRET_ENV}, and that the app is a Production app with Product "
                "Information V4 enabled -- a Sandbox app fails here."
            )
        if resp.status_code != 200:
            raise DigiKeyError(
                self._redact(
                    f"Digi-Key token request failed ({resp.status_code}): {resp.text[:300]}"
                )
            )

        payload = self._json_body(resp, "token request")
        token = payload.get("access_token")
        if not token:
            raise DigiKeyError("Digi-Key returned no access_token")
        # Refresh a minute early so a request cannot start on a token that
        # expires mid-flight.
        self._token = token
        self._token_expires_at = time.time() + _as_float(payload.get("expires_in"), 1800.0) - 60
        return token

    def _valid_token(self) -> str:
        if self._token and time.time() < self._token_expires_at:
            return self._token
        return self._fetch_token()

    def _headers(self, token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "X-DIGIKEY-Client-Id": self._client_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-DIGIKEY-Locale-Site": self.locale["site"],
            "X-DIGIKEY-Locale-Language": self.locale["language"],
            "X-DIGIKEY-Locale-Currency": self.locale["currency"],
        }

    def search_keyword(self, keywords: str, limit: int = 10, offset: int = 0) -> Dict[str, Any]:
        """POST /products/v4/search/keyword, refreshing the token if it is stale."""
        body = {"Keywords": keywords, "Limit": max(1, min(int(limit), 50)), "Offset": int(offset)}
        for attempt in (1, 2):
            token = self._valid_token()
            self._sleep_for_rate_limit()
            try:
                resp = requests.post(
                    KEYWORD_SEARCH_URL,
                    json=body,
                    headers=self._headers(token),
                    timeout=self.timeout,
                )
            except requests.exceptions.RequestException as e:
                raise DigiKeyError(self._redact(f"Could not reach Digi-Key: {e}"))

            if resp.status_code == 401 and attempt == 1:
                # Expired earlier than advertised; one forced refresh, then give up.
                self._token = None
                continue
            if resp.status_code == 429 and attempt == 1:
                time.sleep(_retry_after_seconds(_header(resp, "Retry-After")))
                continue
            if resp.status_code == 404:
                raise DigiKeyError(
                    "Digi-Key returned 404 for a keyword search. This is usually missing "
                    "locale headers rather than a wrong URL; the client sends site="
                    f"{self.locale['site']}, language={self.locale['language']}, "
                    f"currency={self.locale['currency']}."
                )
            if resp.status_code != 200:
                raise DigiKeyError(
                    self._redact(f"Digi-Key search failed ({resp.status_code}): {resp.text[:300]}")
                )
            return self._json_body(resp, "keyword search")
        raise DigiKeyError("Digi-Key search failed after a token refresh")


def _pick_variation(variations: Sequence[Dict[str, Any]], prefer: Optional[str]) -> Dict[str, Any]:
    """Choose the packaging variation to quote, honouring localized names."""
    if not variations:
        return {}
    if prefer:
        wanted = PACKAGING_SYNONYMS.get(prefer.upper(), (prefer.lower(),))
        for variation in variations:
            name = str(_sub(variation, "PackageType").get("Name", "")).lower()
            if any(w in name for w in wanted):
                return variation
    return variations[0]


def normalize_product(
    product: Dict[str, Any], prefer_packaging: Optional[str] = None
) -> Dict[str, Any]:
    """Flatten one V4 product into the shape the tools return."""
    raw_variations = product.get("ProductVariations") or []
    variations = [v for v in raw_variations if isinstance(v, dict)]
    chosen = _pick_variation(variations, prefer_packaging)
    status = _sub(product, "ProductStatus")
    return {
        "mpn": product.get("ManufacturerProductNumber", ""),
        "manufacturer": _sub(product, "Manufacturer").get("Name", ""),
        "digikeyPartNumber": chosen.get("DigiKeyProductNumber", ""),
        "packaging": _sub(chosen, "PackageType").get("Name", ""),
        "description": _sub(product, "Description").get("ProductDescription", ""),
        "statusId": status.get("Id"),
        "status": status.get("Status", ""),
        "active": status.get("Id") == ACTIVE_STATUS_ID,
        "quantityAvailable": product.get("QuantityAvailable", 0),
        "unitPrice": product.get("UnitPrice"),
        "marketplace": product.get("Marketplace"),
        "datasheet": product.get("DatasheetUrl", ""),
        "productUrl": product.get("ProductUrl", ""),
        "parameters": [
            {"name": p.get("ParameterText", ""), "value": p.get("ValueText", "")}
            for p in (product.get("Parameters") or [])
            if isinstance(p, dict)
        ],
        "variations": [
            {
                "digikeyPartNumber": v.get("DigiKeyProductNumber", ""),
                "packaging": _sub(v, "PackageType").get("Name", ""),
                "minimumOrderQuantity": v.get("MinimumOrderQuantity"),
                "pricing": [
                    {"quantity": b.get("BreakQuantity"), "unitPrice": b.get("UnitPrice")}
                    for b in (v.get("StandardPricing") or [])
                    if isinstance(b, dict)
                ],
            }
            for v in variations
        ],
    }


# One client per resolved locale, so a run of tool calls shares one OAuth token
# instead of buying a fresh one -- and one .env read -- for each. Digi-Key tokens
# last 30 minutes and the token endpoint is itself rate limited, so a client per
# call doubled the request count against the tightest limit in the API.
_CLIENTS: Dict[Tuple[str, str, str], DigiKeyClient] = {}


def _resolve_locale(params: Dict[str, Any]) -> Dict[str, str]:
    given = params.get("locale")
    if isinstance(given, dict) and given:
        return {
            field: str(given.get(field) or default) for field, (_env, default) in LOCALE_ENV.items()
        }
    return {field: os.environ.get(env, default) for field, (env, default) in LOCALE_ENV.items()}


def reset_client_cache() -> None:
    """Drop every memoized client. Exposed for tests, which swap credentials."""
    _CLIENTS.clear()


def _client(params: Dict[str, Any]) -> DigiKeyClient:
    locale = _resolve_locale(params)
    key = (locale["site"], locale["language"], locale["currency"])
    cached = _CLIENTS.get(key)
    # A cached client holds the credentials it was built with, so an operator who
    # fixes DIGIKEY_CLIENT_SECRET mid-session must not keep hitting the old one.
    if cached is not None and cached.matches_environment_credentials():
        return cached
    client = DigiKeyClient(locale=locale)
    # Only a configured client is worth keeping: caching an unconfigured one
    # would stop _load_env_file from ever noticing a .env added later.
    if client.has_credentials():
        _CLIENTS[key] = client
    return client


def _not_configured() -> Dict[str, Any]:
    return {
        "success": False,
        "message": (
            f"Digi-Key credentials not configured. Set {CLIENT_ID_ENV} and "
            f"{CLIENT_SECRET_ENV} in the environment, or put them in a .env at the repo "
            "root (already gitignored). Credentials are never accepted as tool arguments."
        ),
        "requiredEnvironmentVariables": [CLIENT_ID_ENV, CLIENT_SECRET_ENV],
    }


def digikey_test_connection(params: Dict[str, Any]) -> Dict[str, Any]:
    """Check that the configured credentials can obtain a token and run a search."""
    params = params or {}
    client = _client(params)
    if not client.has_credentials():
        return _with_warning(_not_configured(), params)
    try:
        data = client.search_keyword("RC0402FR-0710KL", limit=1)
    except DigiKeyError as e:
        return _with_warning({"success": False, "message": str(e)}, params)
    return _with_warning(
        {
            "success": True,
            "message": "Digi-Key credentials work",
            "locale": client.locale,
            "productsReturned": len(data.get("Products") or []),
        },
        params,
    )


def digikey_search_parts(params: Dict[str, Any]) -> Dict[str, Any]:
    """Keyword search: a part number, an MPN, or a parametric phrase."""
    keywords = str(params.get("keywords", "")).strip()
    if not keywords:
        return _with_warning({"success": False, "message": "keywords is required"}, params)

    client = _client(params)
    if not client.has_credentials():
        return _with_warning(_not_configured(), params)

    prefer = params.get("preferPackaging")
    try:
        data = client.search_keyword(
            keywords,
            limit=_as_int(params.get("limit"), 10),
            offset=_as_int(params.get("offset"), 0),
        )
    except DigiKeyError as e:
        return _with_warning({"success": False, "message": str(e)}, params)

    products = [
        normalize_product(p, prefer) for p in (data.get("Products") or []) if isinstance(p, dict)
    ]
    return _with_warning(
        {
            "success": True,
            "message": (
                f"{len(products)} result(s) for '{keywords}'"
                if products
                else f"Digi-Key has no match for '{keywords}'"
            ),
            "keywords": keywords,
            "exactMatches": data.get("ExactMatches", 0),
            "productsCount": data.get("ProductsCount", len(products)),
            "products": products,
        },
        params,
    )


def _classify(product: Optional[Dict[str, Any]]) -> str:
    if product is None:
        return "not_found"
    if not product["active"]:
        # The status string is localized, so the id decides and the string is
        # passed through for the human reading the report.
        return "inactive"
    if (product["quantityAvailable"] or 0) <= 0:
        return "no_stock"
    if not product["digikeyPartNumber"]:
        # Active, in stock, and no orderable number: the part number lives on
        # ProductVariations and there are none. Calling that "available" hides
        # the row from needsAttention exactly when someone has to go and find
        # out what to actually put on the order.
        return "not_orderable"
    return "available"


def digikey_check_library_availability(params: Dict[str, Any]) -> Dict[str, Any]:
    """Look up every symbol in a .kicad_sym and report lifecycle and stock.

    Costs up to two rate-limited requests per symbol -- the MPN fallback buys a
    second one whenever the distributor number misses -- plus one token request,
    and the client throttles itself between them. ``maxSymbols`` defaults to
    ``DEFAULT_MAX_SYMBOLS`` for that reason.

    A symbol whose lookup fails is reported as ``state: "error"`` with the
    redacted message and the sweep continues, so a single transient failure does
    not discard the rows already paid for. ``MAX_CONSECUTIVE_SWEEP_ERRORS``
    failures in a row stop the sweep, since a revoked key fails identically for
    every remaining symbol.
    """
    lib_path = Path(params.get("libraryPath", ""))
    if not lib_path.is_file():
        return _with_warning(
            {"success": False, "message": f"Library not found: {lib_path}"}, params
        )
    try:
        text = lib_path.read_text(encoding="utf-8")
    except OSError as e:
        return _with_warning(
            {"success": False, "message": f"Could not read {lib_path}: {e}"}, params
        )

    root = _HEAD.search(text)
    if not root or root.group(1) != "kicad_symbol_lib":
        found = root.group(1) if root else "nothing"
        return _with_warning(
            {
                "success": False,
                "message": (
                    f"{lib_path.name} is not a symbol library "
                    f"(root form is '{found}', expected 'kicad_symbol_lib')"
                ),
            },
            params,
        )

    entries = read_symbol_part_numbers(text)
    wanted = params.get("symbols")
    if wanted:
        wanted_set = set(wanted)
        entries = [e for e in entries if e["name"] in wanted_set]

    # A zero or negative cap otherwise slices from the end of the list and
    # reports a truncated sweep of nothing.
    max_symbols = max(1, _as_int(params.get("maxSymbols"), DEFAULT_MAX_SYMBOLS))
    truncated = len(entries) > max_symbols
    entries = entries[:max_symbols]

    client = _client(params)
    if not client.has_credentials():
        return _with_warning(_not_configured(), params)

    prefer_mpn = bool(params.get("searchByMpnFirst", False))
    results: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    consecutive_errors = 0
    aborted: Optional[str] = None

    for entry in entries:
        order = (
            [entry["mpn"], entry["supplierPartNumber"]]
            if prefer_mpn
            else [entry["supplierPartNumber"], entry["mpn"]]
        )
        terms = [t for t in order if t]
        if not terms:
            results.append({"symbol": entry["name"], "state": "no_part_number", "searchTerm": ""})
            counts["no_part_number"] = counts.get("no_part_number", 0) + 1
            continue

        product = None
        used = terms[0]
        failure: Optional[str] = None
        for term in terms:
            used = term
            try:
                data = client.search_keyword(term, limit=1)
            except DigiKeyError as e:
                # One 500, one DNS blip or a second consecutive 429 used to
                # discard every lookup already paid for and force the whole
                # sweep to be repeated. Record it on the row and carry on.
                failure = str(e)
                break
            found = data.get("Products") or []
            if found:
                product = normalize_product(found[0], params.get("preferPackaging"))
                break

        row: Dict[str, Any] = {
            "symbol": entry["name"],
            "state": "error" if failure else _classify(product),
            "searchTerm": used,
            "searchedBy": "mpn" if used == entry["mpn"] else "supplierPartNumber",
        }
        counts[row["state"]] = counts.get(row["state"], 0) + 1

        if failure:
            row["message"] = failure
            results.append(row)
            consecutive_errors += 1
            if consecutive_errors >= MAX_CONSECUTIVE_SWEEP_ERRORS:
                # A revoked key or a hard outage fails identically for every
                # remaining symbol, so stop rather than pay for all of them.
                aborted = (
                    f"stopped after {consecutive_errors} consecutive failures; "
                    f"{len(entries) - len(results)} symbol(s) not checked"
                )
                break
            continue

        consecutive_errors = 0
        if product:
            row.update(
                {
                    "digikeyPartNumber": product["digikeyPartNumber"],
                    "mpn": product["mpn"],
                    "manufacturer": product["manufacturer"],
                    "status": product["status"],
                    "statusId": product["statusId"],
                    "quantityAvailable": product["quantityAvailable"],
                    "unitPrice": product["unitPrice"],
                }
            )
        results.append(row)

    errors = counts.get("error", 0)
    needs_attention = [r for r in results if r["state"] not in ("available",)]
    message = (
        f"Checked {len(results)} symbol(s): "
        + ", ".join(f"{n} {state}" for state, n in sorted(counts.items()))
        if results
        else "No symbols to check"
    )
    if truncated:
        message += f" (stopped at maxSymbols={max_symbols})"
    if aborted:
        message += f" ({aborted})"

    return _with_warning(
        {
            # Partial results are still worth having, so an error on some rows
            # is a successful sweep with those rows marked. Only a sweep that
            # produced nothing usable is a failed one.
            "success": errors == 0 or errors < len(results),
            "message": message,
            "libraryPath": str(lib_path),
            "checked": len(results),
            "truncated": truncated,
            "aborted": aborted,
            "errors": errors,
            "counts": counts,
            "needsAttention": [r["symbol"] for r in needs_attention],
            "results": results,
        },
        params,
    )
