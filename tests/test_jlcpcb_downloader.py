"""
Regression tests for the JLCPCB prebuilt-catalog downloader (issue #199).

These tests do NOT hit the network. They build a small SQLite source that
mimics CDFER's schema (incl. the v_components view and bare-integer lcsc) and
verify that convert_source_sqlite() produces a database in the schema that
JLCPCBPartsManager consumes, plus that download_database() falls through
sources gracefully when none are usable.
"""

import json
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
