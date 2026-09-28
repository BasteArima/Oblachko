"""Translation cache: page results keyed by image hash + language + model, stored in SQLite."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path


class ResultCache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute("CREATE TABLE IF NOT EXISTS results (key TEXT PRIMARY KEY, result TEXT NOT NULL, created REAL NOT NULL)")
            self._db.commit()

    def get(self, key: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT result FROM results WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, result: dict) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO results (key, result, created) VALUES (?, ?, ?)",
                (key, json.dumps(result, ensure_ascii=False), time.time()),
            )
            self._db.commit()

    def clear(self) -> int:
        with self._lock:
            count = self._db.execute("DELETE FROM results").rowcount
            self._db.commit()
        return count
