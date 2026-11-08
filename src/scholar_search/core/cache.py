"""Local response cache backed by SQLite.

Keys are opaque strings built by the service; values are JSON-serialisable
mappings. The cache lives under the private runtime directory, never in the
repository.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import app_home

DEFAULT_TTL_SECONDS = 7 * 24 * 3600


class Cache:
    def __init__(
        self,
        path: Path | None = None,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = path or (app_home() / "cache" / "cache.sqlite3")
        self._ttl = ttl_seconds
        self._clock = clock

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path)
        # WAL lets a reader and a writer coexist. Without it, two `wensu` processes
        # running at once can trip "database is locked", and the loser gets no cache
        # rather than a slightly stale read.
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS cache ("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL, created REAL NOT NULL)"
        )
        return connection

    def get(self, key: str) -> Any | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value, created FROM cache WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        value, created = row
        if self._clock() - float(created) > self._ttl:
            self.delete(key)
            return None
        return json.loads(value)

    def set(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO cache (key, value, created) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "created = excluded.created",
                (key, payload, self._clock()),
            )

    def delete(self, key: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM cache WHERE key = ?", (key,))

    def clear(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM cache")
