"""JSONL audit log.

Only structural facts are recorded: channel, purpose, verb, outcome, duration,
error code. Page content, queries, cookies and account identifiers never reach
this file.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import app_home


class AuditLog:
    def __init__(
        self,
        path: Path | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._path = path or (app_home() / "audit" / "audit.jsonl")
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def path(self) -> Path:
        return self._path

    def write(self, event: str, **fields: Any) -> None:
        record = {"ts": self._clock().isoformat(), "event": event, **fields}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            # Losing an audit line must not abort a user's search.
            pass

    def action(
        self,
        *,
        channel: str,
        purpose: str,
        verb: str,
        ok: bool,
        duration_ms: int,
        error: str | None = None,
    ) -> None:
        fields: dict[str, Any] = {
            "channel": channel,
            "purpose": purpose,
            "verb": verb,
            "ok": ok,
            "duration_ms": duration_ms,
        }
        if error:
            fields["error"] = error[:120]
        self.write("action", **fields)

    def risk(self, *, channel: str, signal: str, cooldown_until: str | None) -> None:
        self.write(
            "risk",
            channel=channel,
            signal=signal,
            cooldown_until=cooldown_until,
        )
