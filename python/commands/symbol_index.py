"""Persistent on-disk symbol index for the symbol library manager.

The in-memory symbol cache (SymbolLibraryManager.symbol_cache) is
process-lifetime only: every backend restart re-parses every .kicad_sym
library (~230 on a stock install), and use_project() discards the whole
cache whenever the project changes. This module adds a shared, mtime+size
validated JSON store so parses survive restarts and manager rebuilds; only
stale entries are re-parsed.

Multi-process note: concurrent MCP server instances share the same store
file; writes are atomic (tmp + os.replace) and last-flush-wins, which is
acceptable for a cache whose entries are self-validating by (mtime, size).

The store is loaded lazily on first use — never at import or __init__ time,
which sits on the backend's READY-handshake critical path.
"""

import atexit
import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.platform_helper import PlatformHelper

logger = logging.getLogger("kicad_interface")

VERSION = 1  # bump when SymbolInfo's persisted shape changes incompatibly


def _default_index_path() -> Path:
    env_override = os.environ.get("KICAD_MCP_SYMBOL_INDEX")
    if env_override:
        return Path(env_override)
    return PlatformHelper.get_cache_dir() / "symbol_index.json"


class SymbolIndexStore:
    """mtime/size-validated persistent JSON index of parsed symbol libraries.

    Structure on disk::

        {"version": 1,
         "entries": {"/abs/path/lib.kicad_sym":
                        {"mtime": ..., "size": ..., "symbols": [{...}, ...]}}}
    """

    #: minimum seconds between non-forced flushes (a warm-up pass parses
    #: hundreds of libraries; flushing the whole index per parse is O(n^2) I/O)
    FLUSH_DEBOUNCE_S = 5.0

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path is not None else _default_index_path()
        self._lock = threading.Lock()
        self._entries: Optional[Dict[str, Any]] = None  # lazy-loaded
        self._dirty = False
        self._last_flush = 0.0
        atexit.register(self.flush, force=True)

    # -- internal ----------------------------------------------------------

    def _load_locked(self) -> Dict[str, Any]:
        """Load the store from disk (caller holds the lock)."""
        if self._entries is not None:
            return self._entries
        entries: Dict[str, Any] = {}
        try:
            if self.path.is_file():
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and data.get("version") == VERSION:
                    loaded = data.get("entries")
                    if isinstance(loaded, dict):
                        entries = loaded
                else:
                    logger.info(
                        "Symbol index at %s has version %r (want %r); rebuilding",
                        self.path,
                        data.get("version") if isinstance(data, dict) else None,
                        VERSION,
                    )
        except Exception as e:
            logger.warning("Corrupt symbol index at %s (%s); starting empty", self.path, e)
        self._entries = entries
        return entries

    @staticmethod
    def _stat_key(library_path: str) -> Optional[Dict[str, Any]]:
        try:
            st = os.stat(library_path)
        except OSError:
            return None
        return {"mtime": st.st_mtime, "size": st.st_size}

    # -- public API ---------------------------------------------------------

    def get(self, library_path: str) -> Optional[List[Any]]:
        """Return cached SymbolInfo list for ``library_path`` if fresh, else None.

        Freshness = both mtime AND size match (mtime alone has 1s-granularity
        risk on some filesystems). Rehydration filters unknown fields so a
        schema drift degrades to a re-parse rather than a crash.
        """
        from commands.library_symbol import SymbolInfo

        key = str(Path(library_path).resolve())
        stat = self._stat_key(key)
        if stat is None:
            return None
        with self._lock:
            entry = self._load_locked().get(key)
        if not entry:
            return None
        if entry.get("mtime") != stat["mtime"] or entry.get("size") != stat["size"]:
            return None
        try:
            valid_fields = {f.name for f in fields(SymbolInfo)}
            return [
                SymbolInfo(**{k: v for k, v in sym.items() if k in valid_fields})
                for sym in entry.get("symbols", [])
            ]
        except Exception as e:
            logger.warning("Could not rehydrate symbol index entry for %s: %s", key, e)
            return None

    def put(self, library_path: str, symbols: List[Any]) -> None:
        """Record the parsed symbols for ``library_path`` (in memory)."""
        key = str(Path(library_path).resolve())
        stat = self._stat_key(key)
        if stat is None:
            return
        entry = {
            "mtime": stat["mtime"],
            "size": stat["size"],
            "symbols": [asdict(s) for s in symbols],
        }
        with self._lock:
            self._load_locked()[key] = entry
            self._dirty = True

    def invalidate(self, library_path: str) -> None:
        """Drop the entry for ``library_path``."""
        key = str(Path(library_path).resolve())
        with self._lock:
            if self._load_locked().pop(key, None) is not None:
                self._dirty = True

    def flush(self, force: bool = False) -> None:
        """Write the store to disk atomically. Never raises.

        Non-forced flushes are debounced (FLUSH_DEBOUNCE_S) and skipped when
        nothing changed: the warm-up thread calls flush after every parsed
        library, and rewriting a multi-MB index hundreds of times per warm
        would be quadratic I/O. Deferred data is flushed by the next flush
        call after the window, by the warm-completion flush(force=True), or
        by the atexit hook.
        """
        try:
            with self._lock:
                if not self._dirty:
                    return
                if not force and (time.monotonic() - self._last_flush) < self.FLUSH_DEBOUNCE_S:
                    return  # stays dirty; a later flush picks it up
                entries = self._load_locked()
                payload = {"version": VERSION, "entries": entries}
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd, tmp_path = tempfile.mkstemp(
                    dir=str(self.path.parent), prefix=".symidx-", suffix=".json"
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(payload, f)
                    os.replace(tmp_path, self.path)
                    self._dirty = False
                    self._last_flush = time.monotonic()
                except Exception:
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                    raise
        except Exception as e:
            logger.warning("Could not flush symbol index to %s: %s", self.path, e)


_default_store: Optional[SymbolIndexStore] = None
_default_store_lock = threading.Lock()


def get_default_store() -> SymbolIndexStore:
    """Process-wide shared store: survives SymbolLibraryManager rebuilds
    (use_project) so a project switch no longer discards parsed libraries."""
    global _default_store
    with _default_store_lock:
        if _default_store is None:
            _default_store = SymbolIndexStore()
        return _default_store
