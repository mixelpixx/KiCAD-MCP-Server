"""
JLCPCB API client for fetching parts data

Handles authentication and downloading the JLCPCB parts library
for integration with KiCAD component selection.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import string
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import requests

logger = logging.getLogger("kicad_interface")


def _load_env_file(env_path: Optional[Path] = None) -> None:
    """Best-effort load of a project-root ``.env`` so JLCPCB_* creds are picked up.

    The MCP server only reads ``os.environ``; it never loaded ``.env`` before, so a
    user who dropped credentials in a (gitignored) ``.env`` saw them silently ignored.
    We load it lazily and non-destructively (never override an already-set env var).

    Args:
        env_path: Path to the ``.env`` file. Defaults to the repo-root ``.env``
            (three parents up from this module); overridable for testing.
    """
    try:
        from dotenv import load_dotenv
    except Exception:  # python-dotenv is a declared dep, but degrade gracefully
        return
    if env_path is None:
        # python/commands/jlcpcb.py -> repo root is three parents up.
        env_path = Path(__file__).resolve().parents[2] / ".env"
    if env_path.is_file():
        load_dotenv(env_path, override=False)


def _library_type_label(raw: Any) -> str:
    """Normalize JLCPCB's library-type strings to Basic / Preferred / Extended.

    The API returns ``base``/``Basic`` for basic parts and ``expand``/``Extended``
    for extended; some responses use ``preferred``. Anything unknown -> Extended.
    """
    val = str(raw or "").strip().lower()
    if val in ("base", "basic"):
        return "Basic"
    if val in ("preferred", "prefer"):
        return "Preferred"
    return "Extended"


def normalize_detail_to_part(detail: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a getComponentDetailByCode item into the JLCPCBPartsManager part shape.

    Produces the same keys ``get_part_info`` returns (so callers/UI stay uniform),
    plus richer live-only fields: ``price_ranges`` (full tiers), ``parameters``,
    ``rohs``, ``eccn_code``, and ``source='live-api'``.

    ``price_breaks`` is deliberately kept in the *same* ``[{qty, price}]`` shape the
    local ``get_part_info`` emits (the TS renderer at ``src/tools/jlcpcb-api.ts``
    reads ``pb.qty`` / ``pb.price``). The verbose per-tier ranges from the API — with
    start/end quantities — are exposed separately under ``price_ranges``.
    """
    price_ranges = detail.get("priceRanges") or []
    # Manager-compatible [{qty, price}] list, keyed on each tier's start quantity.
    price_breaks = [
        {"qty": pr.get("startQuantity", 1), "price": pr.get("unitPrice")}
        for pr in price_ranges
        if pr.get("unitPrice") is not None
    ]
    return {
        "lcsc": detail.get("componentCode"),
        "category": detail.get("firstTypeName", ""),
        "subcategory": detail.get("secondTypeName", ""),
        "mfr_part": detail.get("componentModel", ""),
        "package": detail.get("componentSpecification", ""),
        "solder_joints": detail.get("solderJointCount", 0),
        "manufacturer": detail.get("manufacturer", ""),
        "library_type": _library_type_label(detail.get("libraryType")),
        "description": detail.get("description", ""),
        "datasheet": detail.get("datasheetUrl", ""),
        "stock": detail.get("stockCount", 0),
        "price_json": json.dumps(price_breaks),
        "price_breaks": price_breaks,  # [{qty, price}] — same shape as get_part_info
        "price_ranges": price_ranges,  # full [{startQuantity,endQuantity,unitPrice}]
        "parameters": detail.get("parameters", []),
        "rohs": detail.get("rohsFlag"),
        "eccn_code": detail.get("eccnCode"),
        "assembly_component": detail.get("assemblyComponentFlag"),
        "source": "live-api",
    }


class JLCPCBClient:
    """
    Client for JLCPCB API

    Handles HMAC-SHA256 signature-based authentication and fetching
    the complete parts library from JLCPCB's external API.
    """

    # Legacy bulk-download host (kept for download_full_database compatibility).
    BASE_URL = "https://jlcpcb.com/external"
    # New Open Platform host — real-time component detail / library-list endpoints.
    OPEN_BASE_URL = "https://open.jlcpcb.com"
    DETAIL_PATH = "/overseas/openapi/component/getComponentDetailByCode"
    LIBRARY_LIST_PATH = "/overseas/openapi/component/getComponentLibraryList"

    def __init__(
        self,
        app_id: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
    ):
        """
        Initialize JLCPCB API client

        Args:
            app_id: JLCPCB App ID (or reads from JLCPCB_APP_ID env var)
            access_key: JLCPCB Access Key (or reads from JLCPCB_API_KEY env var)
            secret_key: JLCPCB Secret Key (or reads from JLCPCB_API_SECRET env var)
        """
        _load_env_file()
        self.app_id = app_id or os.getenv("JLCPCB_APP_ID")
        self.access_key = access_key or os.getenv("JLCPCB_API_KEY")
        self.secret_key = secret_key or os.getenv("JLCPCB_API_SECRET")

        if not self.app_id or not self.access_key or not self.secret_key:
            logger.warning(
                "JLCPCB API credentials not found. Set JLCPCB_APP_ID, JLCPCB_API_KEY, and JLCPCB_API_SECRET environment variables."
            )

    @staticmethod
    def _generate_nonce() -> str:
        """Generate a 32-character random nonce"""
        chars = string.ascii_letters + string.digits
        return "".join(secrets.choice(chars) for _ in range(32))

    def _build_signature_string(
        self, method: str, path: str, timestamp: int, nonce: str, body: str
    ) -> str:
        """
        Build the signature string according to JLCPCB spec

        Format:
        <HTTP Method>\n
        <Request Path>\n
        <Timestamp>\n
        <Nonce>\n
        <Request Body>\n

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path with query params
            timestamp: Unix timestamp in seconds
            nonce: 32-character random string
            body: Request body (empty string for GET)

        Returns:
            Signature string
        """
        return f"{method}\n{path}\n{timestamp}\n{nonce}\n{body}\n"

    def _sign(self, signature_string: str) -> str:
        """
        Sign the signature string with HMAC-SHA256

        Args:
            signature_string: The string to sign

        Returns:
            Base64-encoded signature
        """
        signature_bytes = hmac.new(
            self.secret_key.encode("utf-8"), signature_string.encode("utf-8"), hashlib.sha256
        ).digest()
        return base64.b64encode(signature_bytes).decode("utf-8")

    def _get_auth_header(self, method: str, path: str, body: str = "") -> str:
        """
        Generate the Authorization header for JLCPCB API requests

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path with query params
            body: Request body JSON string (empty for GET)

        Returns:
            Authorization header value
        """
        if not self.app_id or not self.access_key or not self.secret_key:
            raise Exception(
                "JLCPCB API credentials not configured. Please set JLCPCB_APP_ID, JLCPCB_API_KEY, and JLCPCB_API_SECRET environment variables."
            )

        nonce = self._generate_nonce()
        timestamp = int(time.time())

        signature_string = self._build_signature_string(method, path, timestamp, nonce, body)
        signature = self._sign(signature_string)

        logger.debug(f"Signature string:\n{repr(signature_string)}")
        logger.debug(f"Signature: {signature}")
        logger.debug(
            f'Auth header: JOP appid="{self.app_id}",accesskey="{self.access_key}",nonce="{nonce}",timestamp="{timestamp}",signature="{signature}"'
        )

        return f'JOP appid="{self.app_id}",accesskey="{self.access_key}",nonce="{nonce}",timestamp="{timestamp}",signature="{signature}"'

    def has_credentials(self) -> bool:
        """True if all three credentials are present (App ID / Access Key / Secret Key)."""
        return bool(self.app_id and self.access_key and self.secret_key)

    def _post_signed(self, base_url: str, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Sign and POST a JSON payload, returning the parsed ``data`` field.

        Shared by the Open Platform endpoints. The signed body string and the wire
        body MUST be byte-identical, so we serialize once with compact separators
        and send it as raw ``data`` (not ``json=``) to avoid re-encoding drift.
        """
        body_str = json.dumps(payload, separators=(",", ":"))
        auth_header = self._get_auth_header("POST", path, body_str)
        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        resp = requests.post(f"{base_url}{path}", headers=headers, data=body_str, timeout=30)
        trace = resp.headers.get("J-Trace-ID")
        logger.debug(f"POST {path} -> HTTP {resp.status_code} (J-Trace-ID={trace})")
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 200:
            raise Exception(
                f"JLCPCB API error (code {data.get('code')}): "
                f"{data.get('message', 'Unknown error')} [J-Trace-ID={trace}]"
            )
        return data.get("data")

    def get_component_detail(self, codes: List[str]) -> List[Dict[str, Any]]:
        """Real-time detail lookup by LCSC C-code(s) via the Open Platform.

        Uses ``getComponentDetailByCode`` (batch, up to 1000 codes per call), which
        returns live stock, tiered pricing, parameters, datasheet and library type.

        Args:
            codes: List of C-codes (e.g. ``["C8734", "C25804"]``). A missing/normalized
                ``C`` prefix is added automatically.

        Returns:
            List of raw detail dicts (see ``normalize_detail_to_part`` to reshape).
        """
        if not codes:
            return []
        # LCSC codes are "C" + digits; upper-case and ensure the C prefix.
        norm = []
        for c in codes:
            s = str(c).strip().upper()
            norm.append(s if s.startswith("C") else f"C{s}")
        # API caps the batch at 1000 codes per request.
        out: List[Dict[str, Any]] = []
        for i in range(0, len(norm), 1000):
            batch = norm[i : i + 1000]
            data = self._post_signed(
                self.OPEN_BASE_URL, self.DETAIL_PATH, {"componentCodes": batch}
            )
            # ``data`` is the list itself on this endpoint (not wrapped in a VOList key
            # in the live response), but tolerate the documented wrapped shape too.
            if isinstance(data, dict):
                data = data.get("componentDetailResponseVOList", [])
            if data:
                out.extend(data)
        return out

    def fetch_parts_page(self, last_key: Optional[str] = None) -> Dict:
        """
        Fetch one page of parts from JLCPCB API

        Args:
            last_key: Pagination key from previous response (None for first page)

        Returns:
            Response dict with parts data and pagination info
        """
        path = "/component/getComponentInfos"

        payload = {}
        if last_key:
            payload["lastKey"] = last_key

        # Convert payload to JSON string for signing
        # For POST requests, we always send JSON, even if empty dict
        body_str = json.dumps(payload, separators=(",", ":"))

        # Generate authorization header
        auth_header = self._get_auth_header("POST", path, body_str)

        headers = {"Authorization": auth_header, "Content-Type": "application/json"}

        try:
            response = requests.post(
                f"{self.BASE_URL}{path}", headers=headers, json=payload, timeout=60
            )

            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response headers: {response.headers}")
            logger.debug(f"Response text: {response.text}")

            response.raise_for_status()
            data = response.json()

            if data.get("code") != 200:
                raise Exception(
                    f"API request failed (code {data.get('code')}): {data.get('msg', 'Unknown error')} - Full response: {data}"
                )

            return data["data"]

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch parts page: {e}")
            raise Exception(f"JLCPCB API request failed: {e}")

    def download_full_database(
        self, callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Dict]:
        """
        Download entire parts library from JLCPCB

        Args:
            callback: Optional progress callback function(current_page, total_parts, status_msg)

        Returns:
            List of all parts
        """
        all_parts = []
        last_key = None
        page = 0

        logger.info("Starting full JLCPCB parts database download...")

        while True:
            page += 1

            try:
                data = self.fetch_parts_page(last_key)

                parts = data.get("componentInfos", [])
                all_parts.extend(parts)

                last_key = data.get("lastKey")

                if callback:
                    callback(page, len(all_parts), f"Downloaded {len(all_parts)} parts...")
                else:
                    logger.info(f"Page {page}: Downloaded {len(all_parts)} parts so far...")

                # Check if there are more pages
                if not last_key or len(parts) == 0:
                    break

                # Rate limiting - be nice to the API
                time.sleep(0.5)

            except Exception as e:
                logger.error(f"Error downloading parts at page {page}: {e}")
                if len(all_parts) > 0:
                    logger.warning(f"Partial download available: {len(all_parts)} parts")
                    return all_parts
                else:
                    raise

        logger.info(f"Download complete: {len(all_parts)} parts retrieved")
        return all_parts

    def get_part_by_lcsc(self, lcsc_number: str) -> Optional[Dict]:
        """
        Get real-time detail for a specific LCSC part number.

        Backed by the Open Platform ``getComponentDetailByCode`` endpoint, so stock
        and pricing are live (not the local snapshot).

        Args:
            lcsc_number: LCSC part number (e.g., "C25804")

        Returns:
            Part info dict (JLCPCBPartsManager shape, via ``normalize_detail_to_part``)
            or None if not found.
        """
        details = self.get_component_detail([lcsc_number])
        if not details:
            return None
        return normalize_detail_to_part(details[0])


def test_jlcpcb_connection(
    app_id: Optional[str] = None, access_key: Optional[str] = None, secret_key: Optional[str] = None
) -> bool:
    """
    Test JLCPCB API connection

    Args:
        app_id: Optional App ID (uses env var if not provided)
        access_key: Optional Access Key (uses env var if not provided)
        secret_key: Optional Secret Key (uses env var if not provided)

    Returns:
        True if connection successful, False otherwise
    """
    try:
        client = JLCPCBClient(app_id, access_key, secret_key)
        # Test by fetching first page
        data = client.fetch_parts_page()
        logger.info("JLCPCB API connection test successful")
        return True
    except Exception as e:
        logger.error(f"JLCPCB API connection test failed: {e}")
        return False


if __name__ == "__main__":
    # Test the JLCPCB client
    logging.basicConfig(level=logging.INFO)

    print("Testing JLCPCB API connection...")
    if test_jlcpcb_connection():
        print("✓ Connection successful!")

        client = JLCPCBClient()
        print("\nFetching first page of parts...")
        data = client.fetch_parts_page()
        parts = data.get("componentInfos", [])
        print(f"✓ Retrieved {len(parts)} parts in first page")

        if parts:
            print(f"\nExample part:")
            part = parts[0]
            print(f"  LCSC: {part.get('componentCode')}")
            print(f"  MFR Part: {part.get('componentModelEn')}")
            print(f"  Category: {part.get('firstSortName')} / {part.get('secondSortName')}")
            print(f"  Package: {part.get('componentSpecificationEn')}")
            print(f"  Stock: {part.get('stockCount')}")
    else:
        print("✗ Connection failed. Check your API credentials.")
