"""A tiny 'have I already handled this episode?' ledger.

This is deliberately the simplest thing that works: a JSON file mapping an
episode ID to a small record of when we first saw it and processed it. On a
single-user Pi there is no need for a real database.

Why a file and not, say, SQLite? Because you can open it in a text editor,
eyeball it, and hand-edit it if something goes wrong — which matters a lot
while you're still building and debugging the pipeline.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class ProcessedStore:
    """Remembers which episode IDs have already been processed.

    Example
    -------
    >>> store = ProcessedStore(Path("data/processed_episodes.json"))
    >>> store.is_processed("abc123")
    False
    >>> store.mark_processed("abc123", title="Ep 42 — Whatever")
    >>> store.is_processed("abc123")
    True
    """

    def __init__(self, path: Path):
        self.path = path
        self._records: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as fh:
                self._records = json.load(fh)

    def _save(self) -> None:
        # Write to a temp file then rename: an atomic swap so a crash mid-write
        # can never leave us with a half-written, corrupt ledger.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(self._records, fh, indent=2, ensure_ascii=False)
        tmp.replace(self.path)

    def is_processed(self, episode_id: str) -> bool:
        return episode_id in self._records

    def mark_processed(self, episode_id: str, *, title: str = "") -> None:
        """Record that an episode has been fully handled by the pipeline."""
        now = datetime.now(timezone.utc).isoformat()
        record = self._records.get(episode_id, {})
        record.setdefault("first_seen", now)
        record["processed_at"] = now
        record["title"] = title or record.get("title", "")
        self._records[episode_id] = record
        self._save()

    def all_ids(self) -> set[str]:
        return set(self._records)
