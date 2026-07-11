"""
JLCSearch API client (public, no authentication required)

Alternative to official JLCPCB API using the community-maintained
jlcsearch service at https://jlcsearch.tscircuit.com/
"""

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Union

import requests

logger = logging.getLogger("kicad_interface")


class JLCSearchClient:
    """
    Client for JLCSearch public API (tscircuit)

    Provides access to JLCPCB parts database without authentication
    via the community-maintained jlcsearch service.
    """

    BASE_URL = "https://jlcsearch.tscircuit.com"

    def __init__(self) -> None:
        """Initialize JLCSearch API client"""
        pass

    def search_components(
        self, category: str = "components", limit: int = 100, offset: int = 0, **filters: Dict
    ) -> List[Dict]:
        """
        Search components in JLCSearch database

        Args:
            category: Component category (e.g., "resistors", "capacitors", "components")
            limit: Maximum number of results
            offset: Offset for pagination
            **filters: Additional filters (e.g., package="0603", resistance=1000)

        Returns:
            List of component dicts
        """
        url = f"{self.BASE_URL}/{category}/list.json"

        params = {"limit": limit, "offset": offset, **filters}

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            # The response has the category name as key
            # e.g., {"resistors": [...]} or {"components": [...]}
            for key, value in data.items():
                if isinstance(value, list):
                    return value

            return []

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to search JLCSearch: {e}")
            raise Exception(f"JLCSearch API request failed: {e}")

    def search_resistors(
        self, resistance: Optional[int] = None, package: Optional[str] = None, limit: int = 100
    ) -> List[Dict]:
        """
        Search for resistors

        Args:
            resistance: Resistance value in ohms
            package: Package type (e.g., "0603", "0805")
            limit: Maximum results

        Returns:
            List of resistor dicts with fields:
            - lcsc: LCSC number (integer)
            - mfr: Manufacturer part number
            - package: Package size
            - is_basic: True if basic library part
            - resistance: Resistance in ohms
            - tolerance_fraction: Tolerance (0.01 = 1%)
            - power_watts: Power rating in mW
            - stock: Available stock
            - price1: Price per unit
        """
        filters: Dict[str, Any] = {}
        if resistance is not None:
            filters["resistance"] = resistance
        if package:
            filters["package"] = package

        return self.search_components("resistors", limit=limit, **filters)

    def search_capacitors(
        self, capacitance: Optional[float] = None, package: Optional[str] = None, limit: int = 100
    ) -> List[Dict]:
        """
        Search for capacitors

        Args:
            capacitance: Capacitance value in farads
            package: Package type
            limit: Maximum results

        Returns:
            List of capacitor dicts
        """
        filters: Dict[str, Any] = {}
        if capacitance is not None:
            filters["capacitance"] = capacitance
        if package:
            filters["package"] = package

        return self.search_components("capacitors", limit=limit, **filters)

    def get_part_by_lcsc(self, lcsc_number: int) -> Optional[Dict]:
        """
        Get part details by LCSC number

        Args:
            lcsc_number: LCSC number (integer, without 'C' prefix)

        Returns:
            Part dict or None if not found
        """
        # Search across all components filtering by LCSC
        # Note: jlcsearch doesn't have a dedicated single-part endpoint
        # so we search and filter
        try:
            results = self.search_components("components", limit=1, lcsc=lcsc_number)
            return results[0] if results else None
        except Exception as e:
            logger.error(f"Failed to get part C{lcsc_number}: {e}")
            return None

    # NOTE: bulk catalog download was removed (issue #199). The JLCSearch
    # endpoint is a *search front-end* that ignores the ``offset`` parameter,
    # so offset-paged "download everything" loops returned the same first 100
    # parts forever. Full-catalog download now uses a prebuilt source via
    # ``commands.jlcpcb_downloader.download_database()``. This client remains
    # for interactive/parametric lookups only (search_components, etc.).


def test_jlcsearch_connection() -> bool:
    """
    Test JLCSearch API connection

    Returns:
        True if connection successful, False otherwise
    """
    try:
        client = JLCSearchClient()
        # Test by searching for 1k resistors
        results = client.search_resistors(resistance=1000, limit=5)
        logger.info(f"JLCSearch API connection test successful - found {len(results)} resistors")
        return True
    except Exception as e:
        logger.error(f"JLCSearch API connection test failed: {e}")
        return False


if __name__ == "__main__":
    # Test the JLCSearch client
    logging.basicConfig(level=logging.INFO)

    print("Testing JLCSearch API connection...")
    if test_jlcsearch_connection():
        print("✓ Connection successful!")

        client = JLCSearchClient()

        print("\nSearching for 1k 0603 resistors...")
        resistors = client.search_resistors(resistance=1000, package="0603", limit=5)
        print(f"✓ Found {len(resistors)} resistors")

        if resistors:
            print(f"\nExample resistor:")
            r = resistors[0]
            print(f"  LCSC: C{r.get('lcsc')}")
            print(f"  MFR: {r.get('mfr')}")
            print(f"  Package: {r.get('package')}")
            print(f"  Resistance: {r.get('resistance')}Ω")
            print(f"  Tolerance: {r.get('tolerance_fraction', 0) * 100}%")
            print(f"  Power: {r.get('power_watts')}mW")
            print(f"  Stock: {r.get('stock')}")
            print(f"  Price: ${r.get('price1')}")
            print(f"  Basic Library: {'Yes' if r.get('is_basic') else 'No'}")
    else:
        print("✗ Connection failed")
