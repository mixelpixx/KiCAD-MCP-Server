"""
Regression tests for JLCPCB FTS search with hyphenated MPNs.

`JLCPCBPartsManager.search_parts()` built its FTS5 MATCH query by appending
``*`` to each whitespace term. A hyphenated MPN like ``SHT41-AD1F-R2`` then
parsed ``-`` as an FTS operator -> ``sqlite3.OperationalError: no such column:
AD1F``, which search_parts swallowed into an empty result — so searching by a
real MPN silently found nothing. These tests build a tiny in-schema database (no
network, no 465MB snapshot) and verify the fix.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

# Match the import root used elsewhere in the test suite (python/ on sys.path).
PYTHON_DIR = Path(__file__).resolve().parent.parent / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from commands.jlcpcb_parts import JLCPCBPartsManager, _build_fts_match_query  # noqa: E402


def _insert(mgr: JLCPCBPartsManager, lcsc, mfr_part, description, manufacturer, stock=1000):
    cur = mgr.conn.cursor()
    cur.execute(
        "INSERT INTO components (lcsc, mfr_part, description, manufacturer, stock, price_json)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (lcsc, mfr_part, description, manufacturer, stock, "[]"),
    )
    cur.execute(
        "INSERT INTO components_fts (rowid, lcsc, description, mfr_part, manufacturer)"
        " SELECT rowid, lcsc, description, mfr_part, manufacturer FROM components WHERE lcsc = ?",
        (lcsc,),
    )
    mgr.conn.commit()


@pytest.fixture()
def manager(tmp_path):
    mgr = JLCPCBPartsManager(db_path=str(tmp_path / "parts.db"))
    _insert(
        mgr,
        "C7461862",
        "SHT41-AD1F-R2",
        "Temperature and humidity sensor I2C",
        "Sensirion",
    )
    _insert(mgr, "C25804", "0603WAF1002T5E", "10kOhms 1% resistor", "UNI-ROYAL", stock=5000)
    yield mgr
    mgr.close()


# ---------------------------------------------------------------------------
# Regression: hyphenated MPN
# ---------------------------------------------------------------------------


def test_hyphenated_mpn_returns_the_part(manager):
    results = manager.search_parts(query="SHT41-AD1F-R2")
    assert [r["lcsc"] for r in results] == ["C7461862"]


def test_raw_hyphenated_query_would_crash_fts(manager):
    # Demonstrates the bug the fix addresses: the pre-fix query string raises.
    with pytest.raises(sqlite3.OperationalError):
        manager.conn.execute(
            "SELECT lcsc FROM components_fts WHERE components_fts MATCH ?",
            ("SHT41-AD1F-R2*",),
        ).fetchall()
    # The sanitized query does not raise and matches.
    safe = _build_fts_match_query("SHT41-AD1F-R2")
    rows = manager.conn.execute(
        "SELECT lcsc FROM components_fts WHERE components_fts MATCH ?", (safe,)
    ).fetchall()
    assert [r[0] for r in rows] == ["C7461862"]


def test_prefix_matching_still_works(manager):
    # "SHT41" (no hyphen) should still prefix-match the MPN.
    results = manager.search_parts(query="SHT41")
    assert [r["lcsc"] for r in results] == ["C7461862"]


def test_multi_term_query_all_terms_must_match(manager):
    # Both terms present -> the sensor; a term absent -> no rows.
    assert [r["lcsc"] for r in manager.search_parts(query="humidity sensor")] == ["C7461862"]
    assert manager.search_parts(query="humidity resistor") == []


def test_embedded_quote_does_not_crash(manager):
    # A stray double quote must not raise; it simply matches nothing here.
    assert manager.search_parts(query='SHT41"weird') == []


def test_search_with_other_filters_and_hyphen(manager):
    results = manager.search_parts(query="SHT41-AD1F-R2", manufacturer="Sensirion")
    assert [r["lcsc"] for r in results] == ["C7461862"]


# ---------------------------------------------------------------------------
# _build_fts_match_query unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query,expected",
    [
        ("SHT41-AD1F-R2", '"SHT41-AD1F-R2"*'),
        ("10k 0603", '"10k"* "0603"*'),
        ("BQ25895*", '"BQ25895"*'),  # caller-supplied trailing * normalized
        ('weird"quote', '"weird""quote"*'),  # embedded quote doubled
        ("   spaced   out  ", '"spaced"* "out"*'),
        ("*", ""),  # nothing left after stripping the star
    ],
)
def test_build_fts_match_query(query, expected):
    assert _build_fts_match_query(query) == expected
