#!/usr/bin/env python3
"""
Download JLCPCB parts database from yaqwsx/jlcparts pre-built cache.

This downloads the full JLCPCB catalog (~421MB compressed, ~1.5GB SQLite)
from GitHub Pages in ~5 minutes instead of the broken JLCSearch API approach.

The cache.sqlite3 file contains all JLCPCB parts with stock, pricing,
and category data. We then convert it into the format expected by the
KiCad MCP server's JLCPCBPartsManager.
"""

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

CACHE_DIR = DATA_DIR / "jlcparts_cache"
CACHE_DIR.mkdir(exist_ok=True)

BASE_URL = "https://yaqwsx.github.io/jlcparts/data"
PARTS = [f"cache.z{i:02d}" for i in range(1, 20)] + ["cache.zip"]

TARGET_DB = DATA_DIR / "jlcpcb_parts.db"


def download_files():
    """Download all split archive parts."""
    print("Downloading jlcparts database (~421MB)...")
    for part in PARTS:
        dest = CACHE_DIR / part
        if dest.exists() and dest.stat().st_size > 1000:
            print(f"  {part} already exists, skipping")
            continue
        url = f"{BASE_URL}/{part}"
        print(f"  Downloading {part}...")
        result = subprocess.run(
            ["curl", "-L", "-o", str(dest), "--progress-bar", url], capture_output=False
        )
        if result.returncode != 0:
            print(f"  ERROR downloading {part}")
            return False
    return True


def extract_database():
    """Extract the split 7z archive to get cache.sqlite3."""
    cache_sqlite = CACHE_DIR / "cache.sqlite3"
    if cache_sqlite.exists() and cache_sqlite.stat().st_size > 100_000_000:
        print(f"cache.sqlite3 already extracted ({cache_sqlite.stat().st_size // (1024*1024)}MB)")
        return True

    print("Extracting archive (requires 7z or p7zip)...")
    # Try 7z first, then 7zz (homebrew)
    for cmd in ["7z", "7zz", "7za"]:
        try:
            result = subprocess.run(
                [cmd, "x", "-y", "-o" + str(CACHE_DIR), str(CACHE_DIR / "cache.zip")],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print(f"Extracted with {cmd}")
                return True
            else:
                print(f"  {cmd} failed: {result.stderr[:200]}")
        except FileNotFoundError:
            continue

    print("\nERROR: 7z not found. Install with: brew install p7zip")
    return False


def convert_to_mcp_format():
    """Convert jlcparts cache.sqlite3 to the MCP server's expected format."""
    source = CACHE_DIR / "cache.sqlite3"
    if not source.exists():
        print("ERROR: cache.sqlite3 not found")
        return False

    print(f"Reading source database...")
    src = sqlite3.connect(str(source))
    src.row_factory = sqlite3.Row

    # Check schema
    tables = [
        r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    ]
    print(f"  Source tables: {tables}")

    # Find the main components table
    comp_table = None
    for t in tables:
        count = src.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
        print(f"    {t}: {count:,} rows")
        if count > 10000 and comp_table is None:
            comp_table = t

    if not comp_table:
        # Try 'components' specifically
        comp_table = "components" if "components" in tables else tables[0]

    # Get column names
    cols = [r[1] for r in src.execute(f"PRAGMA table_info([{comp_table}])").fetchall()]
    print(f"  Using table '{comp_table}' with columns: {cols[:10]}...")

    # Remove old target DB
    if TARGET_DB.exists():
        TARGET_DB.unlink()

    # Create target DB in MCP format
    dst = sqlite3.connect(str(TARGET_DB))
    dst.execute("""
        CREATE TABLE components (
            lcsc TEXT PRIMARY KEY,
            category TEXT,
            subcategory TEXT,
            mfr_part TEXT,
            package TEXT,
            solder_joints INTEGER,
            manufacturer TEXT,
            library_type TEXT,
            description TEXT,
            datasheet TEXT,
            stock INTEGER,
            price_json TEXT,
            last_updated INTEGER
        )
    """)
    dst.execute("CREATE INDEX idx_category ON components(category, subcategory)")
    dst.execute("CREATE INDEX idx_package ON components(package)")
    dst.execute("CREATE INDEX idx_manufacturer ON components(manufacturer)")
    dst.execute("CREATE INDEX idx_library_type ON components(library_type)")
    dst.execute("CREATE INDEX idx_mfr_part ON components(mfr_part)")

    # Map source columns to our schema
    # jlcparts schema varies but commonly has:
    # lcsc, mfr, description, joint, manufacturer, basic, preferred, stock, price, url, etc.
    print(f"\nConverting parts to MCP format...")
    now = int(time.time())
    batch = []
    count = 0

    for row in src.execute(f"SELECT * FROM [{comp_table}]"):
        row_dict = dict(row)

        # Adapt column names (jlcparts uses various schemas)
        lcsc = row_dict.get("lcsc") or row_dict.get("LCSC_Part") or row_dict.get("lcsc_id")
        if lcsc is None:
            continue
        if isinstance(lcsc, int):
            lcsc = f"C{lcsc}"
        elif not str(lcsc).startswith("C"):
            lcsc = f"C{lcsc}"

        mfr_part = row_dict.get("mfr") or row_dict.get("MFR_Part") or row_dict.get("mfr_part") or ""
        package = row_dict.get("package") or row_dict.get("Package") or ""
        manufacturer = row_dict.get("manufacturer") or row_dict.get("Manufacturer") or ""
        description = row_dict.get("description") or row_dict.get("Description") or ""
        stock = row_dict.get("stock") or row_dict.get("Stock") or 0
        category = row_dict.get("category") or row_dict.get("First Category") or ""
        subcategory = row_dict.get("subcategory") or row_dict.get("Second Category") or ""
        datasheet = row_dict.get("datasheet") or row_dict.get("url") or ""

        # Library type
        is_basic = row_dict.get("basic") or row_dict.get("is_basic") or row_dict.get("Basic")
        is_preferred = (
            row_dict.get("preferred") or row_dict.get("is_preferred") or row_dict.get("Preferred")
        )
        if is_basic:
            lib_type = "Basic"
        elif is_preferred:
            lib_type = "Preferred"
        else:
            lib_type = "Extended"

        # Price
        price = row_dict.get("price") or row_dict.get("Price") or 0
        price_json = json.dumps([{"qty": 1, "price": price}] if price else [])

        batch.append(
            (
                str(lcsc),
                category,
                subcategory,
                mfr_part,
                package,
                0,
                manufacturer,
                lib_type,
                description,
                datasheet,
                int(stock) if stock else 0,
                price_json,
                now,
            )
        )

        if len(batch) >= 10000:
            dst.executemany(
                """
                INSERT OR REPLACE INTO components
                (lcsc, category, subcategory, mfr_part, package,
                 solder_joints, manufacturer, library_type, description,
                 datasheet, stock, price_json, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                batch,
            )
            count += len(batch)
            batch = []
            if count % 100000 == 0:
                print(f"  Converted {count:,} parts...")

    if batch:
        dst.executemany(
            """
            INSERT OR REPLACE INTO components
            (lcsc, category, subcategory, mfr_part, package,
             solder_joints, manufacturer, library_type, description,
             datasheet, stock, price_json, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            batch,
        )
        count += len(batch)

    # Build FTS index
    print(f"  Building full-text search index...")
    dst.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS components_fts USING fts5(
            lcsc, description, mfr_part, manufacturer,
            content=components
        )
    """)
    dst.execute("INSERT INTO components_fts(components_fts) VALUES('rebuild')")
    dst.commit()

    # Stats
    total = dst.execute("SELECT COUNT(*) FROM components").fetchone()[0]
    basic = dst.execute("SELECT COUNT(*) FROM components WHERE library_type='Basic'").fetchone()[0]
    extended = dst.execute(
        "SELECT COUNT(*) FROM components WHERE library_type='Extended'"
    ).fetchone()[0]

    dst.close()
    src.close()

    db_size = TARGET_DB.stat().st_size / (1024 * 1024)
    print(f"\nDatabase ready: {TARGET_DB}")
    print(f"  Total parts:    {total:,}")
    print(f"  Basic parts:    {basic:,}")
    print(f"  Extended parts: {extended:,}")
    print(f"  DB size:        {db_size:.1f} MB")
    return True


def main():
    print("=" * 60)
    print("JLCPCB Parts Database Downloader (jlcparts method)")
    print("=" * 60)
    start = time.time()

    if not download_files():
        sys.exit(1)

    if not extract_database():
        sys.exit(1)

    if not convert_to_mcp_format():
        sys.exit(1)

    elapsed = time.time() - start
    print(f"\nTotal time: {elapsed/60:.1f} minutes")
    print("Done! Restart the MCP server (/mcp) to use the new database.")


if __name__ == "__main__":
    main()
