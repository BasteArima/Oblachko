"""Per-title glossary of names, so one character isn't "Наоко" on one page and "Нако" on the next.

The LLM reports the names it translated on every page; new ones are stored as automatic entries.
Entries edited in the extension popup are manual: the LLM never overwrites them, and they are
part of the page cache key, so fixing a name re-translates pages with the fix.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Entry:
    src: str
    dst: str
    manual: bool


class Glossary:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS glossary ("
                " title TEXT NOT NULL, src TEXT NOT NULL, dst TEXT NOT NULL,"
                " manual INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL,"
                " PRIMARY KEY (title, src))"
            )
            self._db.commit()

    def entries(self, title: str) -> list[Entry]:
        with self._lock:
            rows = self._db.execute("SELECT src, dst, manual FROM glossary WHERE title = ? ORDER BY src", (title,)).fetchall()
        return [Entry(src, dst, bool(manual)) for src, dst, manual in rows]

    def relevant(self, title: str, lines: list[str]) -> list[Entry]:
        """Entries whose source name occurs on this page: keeps the prompt short."""
        text = _norm(" ".join(lines))
        return [e for e in self.entries(title) if _norm(e.src) in text]

    def manual_hash(self, title: str) -> str:
        manual = [(e.src, e.dst) for e in self.entries(title) if e.manual]
        return hashlib.sha1(repr(manual).encode()).hexdigest()[:12] if manual else "-"

    def learn(self, title: str, names: list[tuple[str, str]]) -> None:
        """Automatic entries from the LLM: first translation wins, manual ones are never touched."""
        rows = [(title, src.strip(), dst.strip(), time.time()) for src, dst in names if src.strip() and dst.strip()]
        if not rows:
            return
        with self._lock:
            self._db.executemany("INSERT OR IGNORE INTO glossary (title, src, dst, manual, updated) VALUES (?, ?, ?, 0, ?)", rows)
            self._db.commit()

    def replace(self, title: str, entries: list[tuple[str, str]]) -> None:
        """Save the list as edited by the user: every entry becomes manual, missing ones are deleted."""
        now = time.time()
        with self._lock:
            self._db.execute("DELETE FROM glossary WHERE title = ?", (title,))
            self._db.executemany(
                "INSERT OR REPLACE INTO glossary (title, src, dst, manual, updated) VALUES (?, ?, ?, 1, ?)",
                [(title, src.strip(), dst.strip(), now) for src, dst in entries if src.strip() and dst.strip()],
            )
            self._db.commit()


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()
