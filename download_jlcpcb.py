#!/usr/bin/env python3
"""
CLI to download the JLCPCB parts database into the MCP server's local DB.

This is a thin wrapper around ``commands.jlcpcb_downloader`` (the same code the
``download_jlcpcb_database`` MCP tool uses). It downloads a prebuilt catalog and
converts it into ``jlcpcb_parts.db``:

    CDFER single-file SQLite (primary, no 7z) ->
    yaqwsx split-7z (fallback, needs 7z CLI) ->
    official JLCPCB API (optional, if JLCPCB_APP_ID/API_KEY/API_SECRET set)

Usage:
    python download_jlcpcb.py [--source cdfer|yaqwsx|official] [--force]
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "python"))

from commands import jlcpcb_downloader  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the JLCPCB parts database")
    parser.add_argument(
        "--source",
        choices=["cdfer", "yaqwsx", "official"],
        default=None,
        help="Force a single source (default: try cdfer, then yaqwsx, then official)",
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-download even if a database already exists"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("JLCPCB Parts Database Downloader")
    print("=" * 60)
    start = time.time()

    result = jlcpcb_downloader.download_database(
        force=args.force,
        prefer_source=args.source,
        progress=lambda msg: print(f"  {msg}"),
    )

    if not result.get("success"):
        print(f"\nERROR: {result.get('message', 'download failed')}")
        for err in result.get("errors", []):
            print(f"  - {err}")
        sys.exit(1)

    elapsed = time.time() - start
    print(f"\nDatabase ready: {result['db_path']}")
    print(f"  Source:         {result['source']}")
    if result.get("catalog_last_modified"):
        print(f"  Catalog dated:  {result['catalog_last_modified']}")
    print(f"  Total parts:    {result['total_parts']:,}")
    print(f"  Basic parts:    {result['basic_parts']:,}")
    print(f"  Extended parts: {result['extended_parts']:,}")
    print(f"  DB size:        {result['db_size_mb']} MB")
    print(f"\nTotal time: {elapsed / 60:.1f} minutes")
    print("Done! Restart the MCP server (/mcp) to use the new database.")


if __name__ == "__main__":
    main()
