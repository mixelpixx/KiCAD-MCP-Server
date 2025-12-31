"""
JLCPCB API client for fetching parts data

Handles authentication and downloading the JLCPCB parts library
for integration with KiCAD component selection.
"""

import os
import logging
import requests
import time
from typing import Optional, Dict, List, Callable
from pathlib import Path

logger = logging.getLogger('kicad_interface')


class JLCPCBClient:
    """
    Client for JLCPCB API

    Handles authentication and fetching the complete parts library
    from JLCPCB's external API.
    """

    BASE_URL = "https://jlcpcb.com/external"

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        """
        Initialize JLCPCB API client

        Args:
            api_key: JLCPCB API key (or reads from JLCPCB_API_KEY env var)
            api_secret: JLCPCB API secret (or reads from JLCPCB_API_SECRET env var)
        """
        self.api_key = api_key or os.getenv('JLCPCB_API_KEY')
        self.api_secret = api_secret or os.getenv('JLCPCB_API_SECRET')
        self.token = None
        self.token_expiry = 0

        if not self.api_key or not self.api_secret:
            logger.warning("JLCPCB API credentials not found. Set JLCPCB_API_KEY and JLCPCB_API_SECRET environment variables.")

    def authenticate(self) -> str:
        """
        Get authentication token from JLCPCB API

        Returns:
            Authentication token

        Raises:
            Exception if authentication fails
        """
        if not self.api_key or not self.api_secret:
            raise Exception("JLCPCB API credentials not configured. Please set JLCPCB_API_KEY and JLCPCB_API_SECRET environment variables.")

        # Check if we have a valid token
        if self.token and time.time() < self.token_expiry:
            return self.token

        logger.info("Authenticating with JLCPCB API...")

        try:
            response = requests.post(
                f"{self.BASE_URL}/genToken",
                json={
                    "appKey": self.api_key,
                    "appSecret": self.api_secret
                },
                timeout=30
            )

            response.raise_for_status()
            data = response.json()

            if data.get('code') != 200:
                raise Exception(f"Authentication failed: {data.get('msg', 'Unknown error')}")

            self.token = data['data']['token']
            # Tokens typically expire after 2 hours, we'll refresh after 1.5 hours to be safe
            self.token_expiry = time.time() + (90 * 60)

            logger.info("Successfully authenticated with JLCPCB API")
            return self.token

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to authenticate with JLCPCB API: {e}")
            raise Exception(f"JLCPCB API authentication failed: {e}")

    def fetch_parts_page(self, last_key: Optional[str] = None) -> Dict:
        """
        Fetch one page of parts from JLCPCB API

        Args:
            last_key: Pagination key from previous response (None for first page)

        Returns:
            Response dict with parts data and pagination info
        """
        token = self.authenticate()

        headers = {
            "externalApiToken": token
        }

        payload = {}
        if last_key:
            payload["lastKey"] = last_key

        try:
            response = requests.post(
                f"{self.BASE_URL}/component/getComponentInfos",
                headers=headers,
                json=payload,
                timeout=60
            )

            response.raise_for_status()
            data = response.json()

            if data.get('code') != 200:
                raise Exception(f"API request failed: {data.get('msg', 'Unknown error')}")

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


def test_jlcpcb_connection(api_key: Optional[str] = None, api_secret: Optional[str] = None) -> bool:
    """
    Test JLCPCB API connection

    Args:
        api_key: Optional API key (uses env var if not provided)
        api_secret: Optional API secret (uses env var if not provided)

    Returns:
        True if connection successful, False otherwise
    """
    try:
        client = JLCPCBClient(api_key, api_secret)
        token = client.authenticate()
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
