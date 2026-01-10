"""
JLCPCB API client for fetching parts data

Handles authentication and downloading the JLCPCB parts library
for integration with KiCAD component selection.
"""

import os
import logging
import requests
import time
import hmac
import hashlib
import secrets
import string
import base64
import json
from typing import Optional, Dict, List, Callable
from pathlib import Path

logger = logging.getLogger('kicad_interface')


class JLCPCBClient:
    """
    Client for JLCPCB API

    Handles HMAC-SHA256 signature-based authentication and fetching
    the complete parts library from JLCPCB's external API.
    """

    BASE_URL = "https://jlcpcb.com/external"

    def __init__(self, app_id: Optional[str] = None, access_key: Optional[str] = None, secret_key: Optional[str] = None):
        """
        Initialize JLCPCB API client

        Args:
            app_id: JLCPCB App ID (or reads from JLCPCB_APP_ID env var)
            access_key: JLCPCB Access Key (or reads from JLCPCB_API_KEY env var)
            secret_key: JLCPCB Secret Key (or reads from JLCPCB_API_SECRET env var)
        """
        self.app_id = app_id or os.getenv('JLCPCB_APP_ID')
        self.access_key = access_key or os.getenv('JLCPCB_API_KEY')
        self.secret_key = secret_key or os.getenv('JLCPCB_API_SECRET')

        if not self.app_id or not self.access_key or not self.secret_key:
            logger.warning("JLCPCB API credentials not found. Set JLCPCB_APP_ID, JLCPCB_API_KEY, and JLCPCB_API_SECRET environment variables.")

    @staticmethod
    def _generate_nonce() -> str:
        """Generate a 32-character random nonce"""
        chars = string.ascii_letters + string.digits
        return ''.join(secrets.choice(chars) for _ in range(32))

    def _build_signature_string(self, method: str, path: str, timestamp: int, nonce: str, body: str) -> str:
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
            self.secret_key.encode('utf-8'),
            signature_string.encode('utf-8'),
            hashlib.sha256
        ).digest()
        return base64.b64encode(signature_bytes).decode('utf-8')

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
            raise Exception("JLCPCB API credentials not configured. Please set JLCPCB_APP_ID, JLCPCB_API_KEY, and JLCPCB_API_SECRET environment variables.")

        nonce = self._generate_nonce()
        timestamp = int(time.time())

        signature_string = self._build_signature_string(method, path, timestamp, nonce, body)
        signature = self._sign(signature_string)

        logger.debug(f"Signature string:\n{repr(signature_string)}")
        logger.debug(f"Signature: {signature}")
        logger.debug(f"Auth header: JOP appid=\"{self.app_id}\",accesskey=\"{self.access_key}\",nonce=\"{nonce}\",timestamp=\"{timestamp}\",signature=\"{signature}\"")

        return f'JOP appid="{self.app_id}",accesskey="{self.access_key}",nonce="{nonce}",timestamp="{timestamp}",signature="{signature}"'

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
        body_str = json.dumps(payload, separators=(',', ':'))

        # Generate authorization header
        auth_header = self._get_auth_header("POST", path, body_str)

        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json"
        }

        try:
            response = requests.post(
                f"{self.BASE_URL}{path}",
                headers=headers,
                json=payload,
                timeout=60
            )

            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response headers: {response.headers}")
            logger.debug(f"Response text: {response.text}")

            response.raise_for_status()
            data = response.json()

            if data.get('code') != 200:
                raise Exception(f"API request failed (code {data.get('code')}): {data.get('msg', 'Unknown error')} - Full response: {data}")

            return data['data']

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch parts page: {e}")
            raise Exception(f"JLCPCB API request failed: {e}")

    def download_full_database(
        self,
        callback: Optional[Callable[[int, int, str], None]] = None
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

                parts = data.get('componentInfos', [])
                all_parts.extend(parts)

                last_key = data.get('lastKey')

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
        Get detailed information for a specific LCSC part number

        Note: This uses the same endpoint as fetching parts, as JLCPCB doesn't
        have a dedicated single-part endpoint. In practice, you should use
        the local database after initial download.

        Args:
            lcsc_number: LCSC part number (e.g., "C25804")

        Returns:
            Part info dict or None if not found
        """
        # For now, this would require searching through pages
        # In practice, you'd use the local database
        logger.warning("get_part_by_lcsc should use local database, not API")
        return None


def test_jlcpcb_connection(app_id: Optional[str] = None, access_key: Optional[str] = None, secret_key: Optional[str] = None) -> bool:
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


if __name__ == '__main__':
    # Test the JLCPCB client
    logging.basicConfig(level=logging.INFO)

    print("Testing JLCPCB API connection...")
    if test_jlcpcb_connection():
        print("✓ Connection successful!")

        client = JLCPCBClient()
        print("\nFetching first page of parts...")
        data = client.fetch_parts_page()
        parts = data.get('componentInfos', [])
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
