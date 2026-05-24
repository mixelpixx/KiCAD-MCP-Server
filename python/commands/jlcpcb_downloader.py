"""
JLCPCB parts catalog downloader (issue #199).

The old approach paged the community JLCSearch API with an ``offset`` parameter,
but that endpoint is a search front-end that ignores ``offset`` and returns the
same first 100 parts on every page, so a full catalog download was impossible.

This module replaces that with a layered download of a *prebuilt* catalog and
converts it into the schema expected by ``JLCPCBPartsManager``
(``get_data_dir()/jlcpcb_parts.db``):

  1. CDFER (primary)  -- https://github.com/CDFER/jlcpcb-parts-database
       A single, raw, uncompressed SQLite file on GitHub Pages. No 7z/zip
       needed, so this is the reliable cross-platform (incl. Windows) path.
  2. yaqwsx/jlcparts (fallback) -- https://github.com/yaqwsx/jlcparts
       The canonical upstream, published as a split 7z archive. Used only if
       CDFER fails AND a 7z CLI is available.
  3. Official JLCPCB API (optional) -- requires JLCPCB_APP_ID / JLCPCB_API_KEY /
       JLCPCB_API_SECRET. Uses cursor pagination (works correctly).

Data is MIT-licensed via CDFER and yaqwsx/jlcparts; the underlying catalog facts
originate from JLCPCB / LCSC and are subject to their terms.
"""

import json
import logging
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from utils.platform_helper import PlatformHelper

logger = logging.getLogger("kicad_interface")

CDFER_SQLITE_URL = "https://cdfer.github.io/jlcpcb-parts-database/jlcpcb-components.sqlite3"
YAQWSX_BASE_URL = "https://yaqwsx.github.io/jlcparts/data"
YAQWSX_MAX_VOLUMES = 30

ProgressFn = Optional[Callable[[str], None]]


def _progress(progress: ProgressFn, message: str) -> None:
    if progress:
        try:
            progress(message)
        except Exception:  # pragma: no cover - progress must never break a download
            pass
    logger.info(message)


# ---------------------------------------------------------------------------
# Conversion (shared by the CDFER and yaqwsx paths)
# ---------------------------------------------------------------------------


def normalize_price_json(raw: Any) -> str:
    """Normalize a source price value into the manager's ``[{"qty","price"}]`` shape.

    Handles both CDFER/jlcparts JSON arrays (``[{"qFrom","qTo","price"}, ...]``)
    and a bare scalar price. Returns a JSON string (``"[]"`` when no price).
    """
    if raw is None or raw == "":
        return json.dumps([])

    # JSON array string (CDFER / jlcparts store price as TEXT JSON)
    if isinstance(raw, str) and raw.strip().startswith("["):
        try:
            arr = json.loads(raw)
        except (ValueError, TypeError):
            return json.dumps([])
        out: List[Dict[str, Any]] = []
        for item in arr if isinstance(arr, list) else []:
            if not isinstance(item, dict):
                continue
            price = item.get("price")
            if price is None:
                continue
            qty = item.get("qFrom", item.get("qty", 1)) or 1
            out.append({"qty": qty, "price": price})
        return json.dumps(out)

    # Scalar numeric price
    try:
        price_val = float(raw)
    except (TypeError, ValueError):
        return json.dumps([])
    return json.dumps([{"qty": 1, "price": price_val}]) if price_val else json.dumps([])


def _library_type(is_basic: Any, is_preferred: Any) -> str:
    if is_basic:
        return "Basic"
    if is_preferred:
        return "Preferred"
    return "Extended"


def _relation_names(src: sqlite3.Connection) -> List[str]:
    # Include temp objects so the v_components view built by _ensure_components_view
    # (a TEMP view) is visible to _pick_source_relation.
    return [
        r[0]
        for r in src.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view') "
            "UNION SELECT name FROM sqlite_temp_master WHERE type IN ('table','view')"
        ).fetchall()
    ]


def _ensure_components_view(src: sqlite3.Connection) -> None:
    """Create a denormalized ``v_components`` view for yaqwsx-style sources.

    CDFER ships a ``v_components`` view, but yaqwsx's raw ``cache.sqlite3`` (the
    FULL catalog) stores category/manufacturer as IDs in sibling ``categories``
    and ``manufacturers`` tables. Without this join the full-catalog convert
    would leave category/subcategory/manufacturer blank. We build the same view
    shape CDFER exposes so the rest of the converter is source-agnostic.
    """
    names = _relation_names(src)
    if "v_components" in names:
        return
    if not ({"components", "categories", "manufacturers"} <= set(names)):
        return
    comp_cols = {r[1] for r in src.execute("PRAGMA table_info([components])").fetchall()}
    if not ({"category_id", "manufacturer_id"} <= comp_cols):
        return
    try:
        src.execute("""
            CREATE TEMP VIEW v_components AS
            SELECT c.*, cat.category AS category, cat.subcategory AS subcategory,
                   m.name AS manufacturer
            FROM components c
            LEFT JOIN categories cat ON cat.id = c.category_id
            LEFT JOIN manufacturers m ON m.id = c.manufacturer_id
            """)
        logger.info("Built v_components join view for yaqwsx-style source")
    except sqlite3.Error as exc:  # pragma: no cover - defensive
        logger.debug(f"could not build v_components view: {exc}")


def _pick_source_relation(src: sqlite3.Connection) -> str:
    """Choose which table/view to read from the source database.

    Prefers a denormalized ``v_components`` view (CDFER ships one; for yaqwsx we
    build an equivalent in ``_ensure_components_view``). Falls back to the
    largest table.
    """
    names = _relation_names(src)
    if "v_components" in names:
        return "v_components"
    if "components" in names:
        return "components"
    # Fallback: largest table
    best, best_count = None, -1
    for name in names:
        try:
            count = src.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
        except sqlite3.Error:
            continue
        if count > best_count:
            best, best_count = name, count
    if not best:
        raise RuntimeError("No usable table/view found in source database")
    return best


def convert_source_sqlite(
    source_path: Path, target_path: Path, progress: ProgressFn = None
) -> Dict[str, int]:
    """Convert a prebuilt source SQLite (CDFER or yaqwsx) into the MCP schema.

    Writes a fresh ``target_path`` (deleting any existing file) with the
    ``components`` table + FTS index that ``JLCPCBPartsManager`` expects.
    Returns ``{"total","basic","extended"}`` counts.
    """
    source_path = Path(source_path)
    target_path = Path(target_path)
    if not source_path.exists():
        raise FileNotFoundError(f"source database not found: {source_path}")

    src = sqlite3.connect(str(source_path))
    src.row_factory = sqlite3.Row
    try:
        _ensure_components_view(src)
        relation = _pick_source_relation(src)
        _progress(progress, f"Converting from source relation '{relation}'...")

        if target_path.exists():
            target_path.unlink()

        dst = sqlite3.connect(str(target_path))
        try:
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

            now = int(time.time())
            batch: List[Tuple] = []
            count = 0

            insert_sql = """
                INSERT OR REPLACE INTO components
                (lcsc, category, subcategory, mfr_part, package, solder_joints,
                 manufacturer, library_type, description, datasheet, stock,
                 price_json, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            for row in src.execute(f"SELECT * FROM [{relation}]"):
                rd = dict(row)

                lcsc = rd.get("lcsc") or rd.get("LCSC_Part") or rd.get("lcsc_id")
                if lcsc is None:
                    continue
                if isinstance(lcsc, int):
                    lcsc = f"C{lcsc}"
                elif not str(lcsc).startswith("C"):
                    lcsc = f"C{lcsc}"

                mfr_part = rd.get("mfr") or rd.get("MFR_Part") or rd.get("mfr_part") or ""
                package = rd.get("package") or rd.get("Package") or ""
                manufacturer = rd.get("manufacturer") or rd.get("Manufacturer") or ""
                description = rd.get("description") or rd.get("Description") or ""
                stock = rd.get("stock") or rd.get("Stock") or 0
                category = rd.get("category") or rd.get("First Category") or ""
                subcategory = rd.get("subcategory") or rd.get("Second Category") or ""
                datasheet = rd.get("datasheet") or rd.get("url") or ""
                joints = rd.get("joints") or rd.get("solder_joints") or 0

                lib_type = _library_type(
                    rd.get("basic") or rd.get("is_basic") or rd.get("Basic"),
                    rd.get("preferred") or rd.get("is_preferred") or rd.get("Preferred"),
                )
                price_json = normalize_price_json(rd.get("price") or rd.get("Price"))

                batch.append(
                    (
                        str(lcsc),
                        category,
                        subcategory,
                        mfr_part,
                        package,
                        int(joints) if joints else 0,
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
                    dst.executemany(insert_sql, batch)
                    count += len(batch)
                    batch = []
                    if count % 100000 == 0:
                        _progress(progress, f"Converted {count:,} parts...")

            if batch:
                dst.executemany(insert_sql, batch)
                count += len(batch)

            _progress(progress, "Building full-text search index...")
            dst.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS components_fts USING fts5(
                    lcsc, description, mfr_part, manufacturer,
                    content=components
                )
                """)
            dst.execute("INSERT INTO components_fts(components_fts) VALUES('rebuild')")
            dst.commit()

            total = dst.execute("SELECT COUNT(*) FROM components").fetchone()[0]
            basic = dst.execute(
                "SELECT COUNT(*) FROM components WHERE library_type='Basic'"
            ).fetchone()[0]
            extended = dst.execute(
                "SELECT COUNT(*) FROM components WHERE library_type='Extended'"
            ).fetchone()[0]
        finally:
            dst.close()
    finally:
        src.close()

    return {"total": total, "basic": basic, "extended": extended}


# ---------------------------------------------------------------------------
# Source downloads
# ---------------------------------------------------------------------------


def _head_last_modified(url: str) -> Optional[str]:
    try:
        import requests

        resp = requests.head(url, allow_redirects=True, timeout=30)
        if resp.ok:
            return resp.headers.get("Last-Modified")
    except Exception as exc:  # network/dns/etc.
        logger.debug(f"HEAD {url} failed: {exc}")
    return None


def download_cdfer(
    cache_dir: Path, progress: ProgressFn = None, max_retries: int = 5
) -> Tuple[Path, Optional[str]]:
    """Stream-download CDFER's single uncompressed SQLite, with resume + retry.

    Stalls/drops were a recurring complaint, so this uses a read timeout and, on
    a network error, retries while *resuming* from the partial file via an HTTP
    Range request (GitHub Pages supports ranged GETs) instead of restarting.
    Returns (path, last_modified).
    """
    import requests

    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / "cdfer.sqlite3"
    last_modified = _head_last_modified(CDFER_SQLITE_URL)
    _progress(
        progress,
        "Downloading CDFER prebuilt SQLite (~1.5 GB)"
        + (f" [catalog dated {last_modified}]" if last_modified else "")
        + "...",
    )

    attempt = 0
    while True:
        attempt += 1
        resume_from = dest.stat().st_size if dest.exists() else 0
        headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}
        try:
            # (connect timeout, read timeout): a stalled socket raises after 120s
            # of no data, so we can resume rather than hang forever.
            with requests.get(
                CDFER_SQLITE_URL, stream=True, timeout=(30, 120), headers=headers
            ) as resp:
                # If we asked to resume but the server ignored Range (200, not
                # 206), start the file over to avoid a corrupt append.
                if resume_from and resp.status_code == 200:
                    resume_from = 0
                resp.raise_for_status()
                last_modified = last_modified or resp.headers.get("Last-Modified")
                mode = "ab" if resume_from else "wb"
                written = resume_from
                next_mark = ((written // (50 * 1024 * 1024)) + 1) * 50 * 1024 * 1024
                with open(dest, mode) as fh:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        written += len(chunk)
                        if written >= next_mark:
                            _progress(progress, f"Downloaded {written // (1024 * 1024)} MB...")
                            next_mark += 50 * 1024 * 1024
            break  # clean end of stream
        except requests.RequestException as exc:
            if attempt > max_retries:
                raise RuntimeError(
                    f"CDFER download failed after {max_retries} retries: {exc}"
                ) from exc
            have_mb = (dest.stat().st_size // (1024 * 1024)) if dest.exists() else 0
            _progress(
                progress,
                f"Download interrupted ({exc}); resuming from {have_mb} MB "
                f"(attempt {attempt}/{max_retries})...",
            )
            time.sleep(min(2 * attempt, 10))

    if dest.stat().st_size < 1_000_000:
        raise RuntimeError("CDFER download too small to be valid")
    return dest, last_modified


def _find_7z() -> Optional[str]:
    for cmd in ("7z", "7zz", "7za"):
        if shutil.which(cmd):
            return cmd
    return None


def download_yaqwsx(cache_dir: Path, progress: ProgressFn = None) -> Path:
    """Download + extract the yaqwsx split 7z archive. Requires a 7z CLI."""
    import subprocess

    seven_zip = _find_7z()
    if not seven_zip:
        raise RuntimeError("yaqwsx fallback requires a 7z CLI (7z/7zz/7za) which was not found")
    if not shutil.which("curl"):
        raise RuntimeError("yaqwsx fallback requires curl which was not found")

    cache_dir.mkdir(parents=True, exist_ok=True)
    _progress(progress, "Downloading yaqwsx split archive (~421 MB)...")

    def _curl(url: str, dst: Path) -> bool:
        # -C - resumes a partial file; --retry handles transient stalls/drops.
        return (
            subprocess.run(
                [
                    "curl",
                    "-L",
                    "-f",
                    "-C",
                    "-",
                    "--retry",
                    "5",
                    "--retry-delay",
                    "2",
                    "--retry-connrefused",
                    "-o",
                    str(dst),
                    "--progress-bar",
                    url,
                ]
            ).returncode
            == 0
        )

    for i in range(1, YAQWSX_MAX_VOLUMES + 1):
        part = f"cache.z{i:02d}"
        dst = cache_dir / part
        if dst.exists() and dst.stat().st_size > 1000:
            continue
        if not _curl(f"{YAQWSX_BASE_URL}/{part}", dst):
            if dst.exists():
                dst.unlink()
            break

    zip_dst = cache_dir / "cache.zip"
    if not (zip_dst.exists() and zip_dst.stat().st_size > 1000):
        if not _curl(f"{YAQWSX_BASE_URL}/cache.zip", zip_dst):
            raise RuntimeError("failed to download yaqwsx cache.zip")

    _progress(progress, f"Extracting archive with {seven_zip}...")
    result = subprocess.run(
        [seven_zip, "x", "-y", "-o" + str(cache_dir), str(zip_dst)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"7z extraction failed: {result.stderr[:300]}")

    sqlite_path = cache_dir / "cache.sqlite3"
    if not sqlite_path.exists():
        raise RuntimeError("yaqwsx archive did not yield cache.sqlite3")
    return sqlite_path


def _download_official(target: Path, force: bool, progress: ProgressFn) -> Dict[str, Any]:
    """Optional fallback: official JLCPCB API (cursor pagination). Requires creds."""
    from commands.jlcpcb import JLCPCBClient
    from commands.jlcpcb_parts import JLCPCBPartsManager

    client = JLCPCBClient()
    if not (client.app_id and client.access_key and client.secret_key):
        raise RuntimeError("official API credentials not set")

    _progress(progress, "Downloading via official JLCPCB API...")
    parts = client.download_full_database(
        callback=lambda page, total, msg: _progress(progress, msg)
    )
    if force and target.exists():
        target.unlink()

    mgr = JLCPCBPartsManager(db_path=str(target))
    try:
        mgr.import_parts(parts, progress_callback=lambda c, t, m: _progress(progress, m))
        stats = mgr.get_database_stats()
    finally:
        mgr.close()
    return _result(
        "official-api",
        target,
        stats["total_parts"],
        stats["basic_parts"],
        stats["extended_parts"],
        None,
    )


# Warn if the catalog is older than this (CDFER's pipeline has stalled for
# weeks at a time, so a "fresh download" can still be stale data).
STALE_AFTER_DAYS = 14


def _catalog_age_days(last_modified: Optional[str]) -> Optional[int]:
    """Parse an HTTP Last-Modified date and return its age in whole days."""
    if not last_modified:
        return None
    try:
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone

        dt = parsedate_to_datetime(last_modified)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except (TypeError, ValueError):
        return None


def _result(
    source: str,
    target: Path,
    total: int,
    basic: int,
    extended: int,
    last_modified: Optional[str],
) -> Dict[str, Any]:
    db_size_mb = round(target.stat().st_size / (1024 * 1024), 2) if target.exists() else 0
    result: Dict[str, Any] = {
        "success": True,
        "source": source,
        "total_parts": total,
        "basic_parts": basic,
        "extended_parts": extended,
        "db_size_mb": db_size_mb,
        "db_path": str(target),
        "catalog_last_modified": last_modified,
    }
    age_days = _catalog_age_days(last_modified)
    if age_days is not None:
        result["catalog_age_days"] = age_days
        if age_days >= STALE_AFTER_DAYS:
            warning = (
                f"Catalog from '{source}' is ~{age_days} days old (dated {last_modified}). "
                "Its upstream pipeline may have stalled. For fresher data, re-run with "
                "source='yaqwsx' (needs a 7z CLI) or source='official' (needs JLCPCB API creds)."
            )
            result["stale"] = True
            result["warning"] = warning
            logger.warning(warning)
    return result


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def download_database(
    force: bool = False,
    prefer_source: Optional[str] = None,
    progress: ProgressFn = None,
) -> Dict[str, Any]:
    """Download the JLCPCB catalog into ``jlcpcb_parts.db`` using a layered strategy.

    Order: CDFER (primary) -> yaqwsx (if 7z available) -> official API (if creds).
    ``prefer_source`` (``"cdfer"``/``"yaqwsx"``/``"official"``) forces a single source.
    Returns a result dict (see ``_result``) or ``{"success": False, "message": ...}``.

    NOTE: callers that hold an open ``JLCPCBPartsManager`` on the target file must
    close it before calling (the prebuilt paths recreate the file) and reopen after.
    """
    data_dir = PlatformHelper.get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    target = data_dir / "jlcpcb_parts.db"
    cache_dir = data_dir / "jlcparts_cache"

    order = [prefer_source] if prefer_source else ["cdfer", "yaqwsx", "official"]
    errors: List[str] = []

    for src in order:
        try:
            if src == "cdfer":
                src_path, last_mod = download_cdfer(cache_dir, progress)
                stats = convert_source_sqlite(src_path, target, progress)
                _safe_rmtree(cache_dir)
                return _result(
                    "cdfer", target, stats["total"], stats["basic"], stats["extended"], last_mod
                )
            if src == "yaqwsx":
                src_path = download_yaqwsx(cache_dir, progress)
                stats = convert_source_sqlite(src_path, target, progress)
                _safe_rmtree(cache_dir)
                return _result(
                    "yaqwsx", target, stats["total"], stats["basic"], stats["extended"], None
                )
            if src == "official":
                return _download_official(target, force, progress)
            errors.append(f"{src}: unknown source")
        except Exception as exc:
            logger.warning(f"JLCPCB source '{src}' failed: {exc}")
            errors.append(f"{src}: {exc}")
            continue

    return {
        "success": False,
        "message": "All JLCPCB download sources failed. "
        "Install a 7z CLI for the yaqwsx fallback, or set JLCPCB_APP_ID/"
        "JLCPCB_API_KEY/JLCPCB_API_SECRET for the official API.",
        "errors": errors,
    }


def _safe_rmtree(path: Path) -> None:
    try:
        if path.exists():
            shutil.rmtree(path)
    except OSError as exc:  # pragma: no cover - cleanup is best-effort
        logger.debug(f"cache cleanup failed for {path}: {exc}")
