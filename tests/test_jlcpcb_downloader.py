"""
Regression tests for the JLCPCB prebuilt-catalog downloader (issue #199).

These tests do NOT hit the network. They build a small SQLite source that
mimics CDFER's schema (incl. the v_components view and bare-integer lcsc) and
verify that convert_source_sqlite() produces a database in the schema that
JLCPCBPartsManager consumes, plus that download_database() falls through
sources gracefully when none are usable.
"""

import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

# Match the import root used elsewhere in the test suite (python/ on sys.path).
PYTHON_DIR = Path(__file__).resolve().parent.parent / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from commands import jlcpcb_downloader  # noqa: E402


def _make_cdfer_like_source(path: Path) -> None:
    """Create a tiny SQLite mirroring CDFER: components + categories + manufacturers + view."""
    con = sqlite3.connect(str(path))
    con.executescript("""
        CREATE TABLE manufacturers (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE categories (id INTEGER PRIMARY KEY, category TEXT, subcategory TEXT);
        CREATE TABLE components (
            lcsc INTEGER PRIMARY KEY,
            category_id INTEGER,
            mfr TEXT,
            package TEXT,
            joints INTEGER,
            manufacturer_id INTEGER,
            basic INTEGER,
            preferred INTEGER,
            description TEXT,
            datasheet TEXT,
            stock INTEGER,
            price TEXT
        );
        CREATE VIEW v_components AS
            SELECT c.lcsc, c.category_id, cat.category, cat.subcategory, c.mfr,
                   c.package, c.joints, m.name AS manufacturer, c.basic, c.preferred,
                   c.description, c.datasheet, c.stock, c.price
            FROM components c
            JOIN categories cat ON cat.id = c.category_id
            JOIN manufacturers m ON m.id = c.manufacturer_id;
        """)
    con.execute("INSERT INTO manufacturers VALUES (1, 'Yageo')")
    con.execute("INSERT INTO categories VALUES (1, 'Resistors', 'Chip Resistor')")
    # basic part, with CDFER-style price JSON (qFrom/qTo/price)
    con.execute(
        "INSERT INTO components VALUES (25804, 1, 'RC0603FR-071KL', '0603', 2, 1, 1, 0, "
        "'1k 1% 0603 resistor', 'http://ds/25804', 5000, ?)",
        (
            json.dumps(
                [
                    {"qFrom": 1, "qTo": 99, "price": 0.0042},
                    {"qFrom": 100, "qTo": None, "price": 0.0021},
                ]
            ),
        ),
    )
    # extended part, empty price
    con.execute(
        "INSERT INTO components VALUES (11111, 1, 'EXT-PART', '0402', 2, 1, 0, 0, "
        "'extended resistor', '', 12, '[]')"
    )
    con.commit()
    con.close()


def test_convert_source_sqlite_produces_manager_schema(tmp_path):
    source = tmp_path / "cdfer.sqlite3"
    target = tmp_path / "jlcpcb_parts.db"
    _make_cdfer_like_source(source)

    stats = jlcpcb_downloader.convert_source_sqlite(source, target)

    assert stats["total"] == 2
    assert stats["basic"] == 1
    assert stats["extended"] == 1

    con = sqlite3.connect(str(target))
    con.row_factory = sqlite3.Row
    rows = {r["lcsc"]: dict(r) for r in con.execute("SELECT * FROM components")}

    # bare-int lcsc must become C-prefixed
    assert "C25804" in rows and "C11111" in rows

    basic = rows["C25804"]
    assert basic["library_type"] == "Basic"
    assert basic["mfr_part"] == "RC0603FR-071KL"  # mfr -> mfr_part
    assert basic["manufacturer"] == "Yageo"  # via v_components view
    assert basic["category"] == "Resistors"
    assert basic["subcategory"] == "Chip Resistor"
    assert basic["stock"] == 5000

    # CDFER price JSON normalized to [{"qty","price"}]
    breaks = json.loads(basic["price_json"])
    assert breaks[0] == {"qty": 1, "price": 0.0042}
    assert breaks[1] == {"qty": 100, "price": 0.0021}

    assert rows["C11111"]["library_type"] == "Extended"
    assert json.loads(rows["C11111"]["price_json"]) == []

    # FTS index exists and is queryable
    fts_hit = con.execute(
        "SELECT lcsc FROM components_fts WHERE components_fts MATCH '1k*'"
    ).fetchall()
    assert any(r[0] == "C25804" for r in fts_hit)
    con.close()


def _make_yaqwsx_like_source(path: Path) -> None:
    """Create a SQLite mirroring yaqwsx's FULL-catalog schema: normalized, NO view.

    category/manufacturer are IDs in sibling tables (no v_components view), which
    is what the real ~10GB cache.sqlite3 looks like.
    """
    con = sqlite3.connect(str(path))
    con.executescript("""
        CREATE TABLE manufacturers (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE categories (id INTEGER PRIMARY KEY, category TEXT, subcategory TEXT);
        CREATE TABLE components (
            lcsc INTEGER PRIMARY KEY,
            category_id INTEGER,
            mfr TEXT,
            package TEXT,
            joints INTEGER,
            manufacturer_id INTEGER,
            basic INTEGER,
            preferred INTEGER,
            description TEXT,
            datasheet TEXT,
            stock INTEGER,
            price TEXT
        );
        """)
    con.execute("INSERT INTO manufacturers VALUES (7, 'Texas Instruments')")
    con.execute("INSERT INTO categories VALUES (3, 'ICs', 'LDO Regulators')")
    con.execute(
        "INSERT INTO components VALUES (12345, 3, 'TLV70033', 'SOT-23-5', 5, 7, 0, 0, "
        "'3.3V LDO', 'http://ds/12345', 0, ?)",
        (json.dumps([{"qFrom": 1, "qTo": None, "price": 0.12}]),),
    )
    con.commit()
    con.close()


def test_convert_yaqwsx_schema_populates_category_and_manufacturer(tmp_path):
    """Full-catalog (yaqwsx) source has no v_components view; the join must be built."""
    source = tmp_path / "cache.sqlite3"
    target = tmp_path / "jlcpcb_parts.db"
    _make_yaqwsx_like_source(source)

    stats = jlcpcb_downloader.convert_source_sqlite(source, target)
    assert stats["total"] == 1

    con = sqlite3.connect(str(target))
    con.row_factory = sqlite3.Row
    row = dict(con.execute("SELECT * FROM components WHERE lcsc='C12345'").fetchone())
    con.close()

    # These would be blank without the built v_components join:
    assert row["category"] == "ICs"
    assert row["subcategory"] == "LDO Regulators"
    assert row["manufacturer"] == "Texas Instruments"
    assert row["mfr_part"] == "TLV70033"
    assert row["library_type"] == "Extended"
    assert json.loads(row["price_json"]) == [{"qty": 1, "price": 0.12}]


def test_normalize_price_json_handles_scalar_and_array_and_empty():
    assert json.loads(jlcpcb_downloader.normalize_price_json(None)) == []
    assert json.loads(jlcpcb_downloader.normalize_price_json("")) == []
    assert json.loads(jlcpcb_downloader.normalize_price_json("[]")) == []
    assert json.loads(jlcpcb_downloader.normalize_price_json(0.05)) == [{"qty": 1, "price": 0.05}]
    arr = json.loads(jlcpcb_downloader.normalize_price_json('[{"qFrom":10,"qTo":50,"price":1.5}]'))
    assert arr == [{"qty": 10, "price": 1.5}]


def test_download_database_falls_through_when_no_source_available(tmp_path, monkeypatch):
    """With CDFER download failing, no 7z present, and no API creds -> clean failure dict."""
    monkeypatch.setattr(
        jlcpcb_downloader.PlatformHelper, "get_data_dir", staticmethod(lambda: tmp_path)
    )

    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(jlcpcb_downloader, "download_cdfer", _boom)
    monkeypatch.setattr(jlcpcb_downloader, "_find_7z", lambda: None)
    # Ensure no official creds leak in from the environment.
    for var in ("JLCPCB_APP_ID", "JLCPCB_API_KEY", "JLCPCB_API_SECRET"):
        monkeypatch.delenv(var, raising=False)

    result = jlcpcb_downloader.download_database()

    assert result["success"] is False
    assert "errors" in result and len(result["errors"]) >= 1
    assert any("cdfer" in e for e in result["errors"])


def test_download_database_prefer_cdfer_converts(tmp_path, monkeypatch):
    """prefer_source='cdfer' downloads then converts via the real conversion path."""
    monkeypatch.setattr(
        jlcpcb_downloader.PlatformHelper, "get_data_dir", staticmethod(lambda: tmp_path)
    )

    def _fake_cdfer(cache_dir, progress=None):
        cache_dir.mkdir(parents=True, exist_ok=True)
        src = cache_dir / "cdfer.sqlite3"
        _make_cdfer_like_source(src)
        return src, "Thu, 02 Apr 2026 06:22:46 GMT"

    monkeypatch.setattr(jlcpcb_downloader, "download_cdfer", _fake_cdfer)

    result = jlcpcb_downloader.download_database(prefer_source="cdfer")

    assert result["success"] is True
    assert result["source"] == "cdfer"
    assert result["total_parts"] == 2
    assert result["basic_parts"] == 1
    assert result["catalog_last_modified"].startswith("Thu, 02 Apr 2026")
    assert (tmp_path / "jlcpcb_parts.db").exists()


def _http_date(days_ago: int) -> str:
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime

    return format_datetime(datetime.now(timezone.utc) - timedelta(days=days_ago))


def test_result_flags_stale_catalog_and_leaves_fresh_alone(tmp_path, monkeypatch):
    """A catalog older than STALE_AFTER_DAYS must be flagged; a fresh one must not."""
    monkeypatch.setattr(
        jlcpcb_downloader.PlatformHelper, "get_data_dir", staticmethod(lambda: tmp_path)
    )

    def _fake_cdfer_dated(http_date):
        def _impl(cache_dir, progress=None):
            cache_dir.mkdir(parents=True, exist_ok=True)
            src = cache_dir / "cdfer.sqlite3"
            _make_cdfer_like_source(src)
            return src, http_date

        return _impl

    # Stale: 60 days old
    monkeypatch.setattr(jlcpcb_downloader, "download_cdfer", _fake_cdfer_dated(_http_date(60)))
    stale = jlcpcb_downloader.download_database(prefer_source="cdfer")
    assert stale.get("stale") is True
    assert "warning" in stale
    assert stale["catalog_age_days"] >= jlcpcb_downloader.STALE_AFTER_DAYS

    # Fresh: 1 day old
    monkeypatch.setattr(jlcpcb_downloader, "download_cdfer", _fake_cdfer_dated(_http_date(1)))
    fresh = jlcpcb_downloader.download_database(prefer_source="cdfer")
    assert fresh.get("stale") is not True
    assert "warning" not in fresh
    assert fresh["catalog_age_days"] <= 1


def test_download_cdfer_skips_when_file_already_complete(tmp_path, monkeypatch):
    """A complete cache file must short-circuit, not re-download (no HTTP 416 loop).

    Regression for the force/resume bug: resuming a complete file sends
    Range: bytes=<size>- which the server answers with 416; the old code retried
    that until failure. With a HEAD size check we return immediately and never
    call requests.get.
    """
    import requests

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    dest = cache_dir / "cdfer.sqlite3"
    payload = b"x" * 4096
    dest.write_bytes(payload)

    class _Head:
        ok = True
        headers = {
            "Content-Length": str(len(payload)),
            "Last-Modified": "Wed, 01 Apr 2026 00:00:00 GMT",
        }

    monkeypatch.setattr(requests, "head", lambda *a, **k: _Head())

    def _no_get(*a, **k):
        raise AssertionError("requests.get must not run when the file is already complete")

    monkeypatch.setattr(requests, "get", _no_get)

    path, last_mod = jlcpcb_downloader.download_cdfer(cache_dir)
    assert path == dest
    assert path.stat().st_size == len(payload)  # untouched
    assert last_mod.startswith("Wed, 01 Apr 2026")


# --------------------------------------------------------------------------- #
# yaqwsx split-archive volume download — count auto-detection
# --------------------------------------------------------------------------- #


def _fake_run_factory(num_volumes, calls=None):
    """Build a subprocess.run stand-in for download_yaqwsx.

    Simulates curl fetching cache.zXX volumes (success for 1..num_volumes, a 404-style
    non-zero for the part past the last volume) and cache.zip, plus 7-Zip extraction
    that materialises cache.sqlite3. Optionally records every curl URL in ``calls``.
    """

    def _run(cmd, *args, **kwargs):
        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        res = _Result()
        if cmd and cmd[0] == "curl":
            url = cmd[-1]
            if calls is not None:
                calls.append(url)
            out = Path(cmd[cmd.index("-o") + 1])
            name = url.rsplit("/", 1)[-1]
            if name == "cache.zip":
                out.write_bytes(b"x" * 2000)
                return res
            m = re.fullmatch(r"cache\.z(\d+)", name)
            if m and int(m.group(1)) <= num_volumes:
                out.write_bytes(b"x" * 2000)
                return res
            res.returncode = 22  # curl -f exits 22 on HTTP 4xx (the 404 past last volume)
            return res
        # Otherwise it's the 7z extraction call: produce cache.sqlite3.
        out_dir = next(c[2:] for c in cmd if isinstance(c, str) and c.startswith("-o"))
        (Path(out_dir) / "cache.sqlite3").write_bytes(b"db")
        return res

    return _run


def test_yaqwsx_autodetects_volume_count_past_old_caps(tmp_path, monkeypatch):
    """The loop must fetch every real volume and stop at the first 404 — not a fixed cap.

    Regression for the hardcoded 30-volume cap: with 40 live volumes it used to fetch
    only z01..z30, leaving the split archive incomplete so 7-Zip extraction failed.
    """
    import subprocess

    monkeypatch.setattr(jlcpcb_downloader, "_find_7z", lambda: "7z")
    monkeypatch.setattr(jlcpcb_downloader.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(40))

    cache = tmp_path / "cache"
    out = jlcpcb_downloader.download_yaqwsx(cache)

    assert out == cache / "cache.sqlite3"
    assert out.exists()
    # All 40 volumes present (proves the loop went well past the old 30/80 caps).
    for i in range(1, 41):
        assert (cache / f"cache.z{i:02d}").exists(), f"missing volume {i}"
    # The 404 probe past the last volume must not leave a partial file behind.
    assert not (cache / "cache.z41").exists()
    assert (cache / "cache.zip").exists()


def test_yaqwsx_skips_existing_volumes_on_rerun(tmp_path, monkeypatch):
    """Re-running with all volumes already present must not re-download them.

    Only the single 404 probe for the volume past the last one should hit curl.
    """
    import subprocess

    cache = tmp_path / "cache"
    cache.mkdir()
    for i in range(1, 41):
        (cache / f"cache.z{i:02d}").write_bytes(b"x" * 2000)
    (cache / "cache.zip").write_bytes(b"x" * 2000)

    monkeypatch.setattr(jlcpcb_downloader, "_find_7z", lambda: "7z")
    monkeypatch.setattr(jlcpcb_downloader.shutil, "which", lambda name: "/usr/bin/" + name)
    calls: list = []
    monkeypatch.setattr(subprocess, "run", _fake_run_factory(40, calls=calls))

    out = jlcpcb_downloader.download_yaqwsx(cache)

    assert out.exists()
    # No existing volume re-downloaded and cache.zip skipped — only the z41 404 probe.
    assert calls == [f"{jlcpcb_downloader.YAQWSX_BASE_URL}/cache.z41"]


def test_yaqwsx_max_volumes_is_a_high_safety_guard():
    """The constant is a runaway-loop guard, not the expected count: it must comfortably
    exceed the current ~41-volume archive so it never truncates a real download."""
    assert jlcpcb_downloader.YAQWSX_MAX_VOLUMES >= 100


# --------------------------------------------------------------------------- #
# 7-Zip resolution (env override -> PATH -> known install dirs)
# --------------------------------------------------------------------------- #


def test_find_7z_delegates_to_resolver(monkeypatch):
    """_find_7z must use the shared resolver (so a 7-Zip off PATH is still found)."""
    monkeypatch.setattr(jlcpcb_downloader, "resolve_7z", lambda: r"C:\Program Files\7-Zip\7z.exe")
    assert jlcpcb_downloader._find_7z() == r"C:\Program Files\7-Zip\7z.exe"


def test_download_yaqwsx_raises_clear_error_when_no_7z(tmp_path, monkeypatch):
    """With no 7-Zip resolvable, download_yaqwsx must raise the multi-location message,
    not the bare 'not found'."""
    monkeypatch.setattr(jlcpcb_downloader, "resolve_7z", lambda: None)

    with pytest.raises(RuntimeError) as exc:
        jlcpcb_downloader.download_yaqwsx(tmp_path / "cache")

    msg = str(exc.value)
    assert "Could not locate a 7-Zip CLI" in msg
    assert "SEVEN_ZIP" in msg


def test_download_yaqwsx_uses_resolved_absolute_7z_path(tmp_path, monkeypatch):
    """download_yaqwsx must invoke the resolved (absolute) 7-Zip path for extraction."""
    import subprocess

    seven_zip = r"C:\Program Files\7-Zip\7z.exe"
    monkeypatch.setattr(jlcpcb_downloader, "resolve_7z", lambda: seven_zip)
    monkeypatch.setattr(jlcpcb_downloader.shutil, "which", lambda name: "/usr/bin/" + name)

    extract_cmds: list = []

    def _run(cmd, *args, **kwargs):
        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        r = _R()
        if cmd and cmd[0] == "curl":
            out = Path(cmd[cmd.index("-o") + 1])
            name = cmd[-1].rsplit("/", 1)[-1]
            if name == "cache.zip" or name == "cache.z01":
                out.write_bytes(b"x" * 2000)
                return r
            r.returncode = 22  # 404 past last volume
            return r
        # 7-Zip extraction call.
        extract_cmds.append(cmd[0])
        out_dir = next(c[2:] for c in cmd if isinstance(c, str) and c.startswith("-o"))
        (Path(out_dir) / "cache.sqlite3").write_bytes(b"db")
        return r

    monkeypatch.setattr(subprocess, "run", _run)

    out = jlcpcb_downloader.download_yaqwsx(tmp_path / "cache")

    assert out.exists()
    assert extract_cmds == [seven_zip]  # the absolute path was used, not a bare "7z"
