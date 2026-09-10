"""The episode ledger — a tiny 'what have I seen and what's done?' database.

This is deliberately the simplest thing that works: one JSON file mapping an
episode ID to a record. It plays two roles at once:

  * a TO-DO QUEUE  — episodes we've caught playing but not yet processed
                     (status == "detected"), and
  * a DONE LEDGER  — episodes fully run through the pipeline
                     (status == "processed").

Why a file and not, say, SQLite? Because you can open it in a text editor,
eyeball it, and hand-edit it if something goes wrong — which matters a lot
while you're still building and debugging the pipeline on a headless Pi.

Everyday analogy: think of it as a paper logbook by the door. Each time you
notice an episode playing you jot down its name and tick "seen again". Later,
when you've fully written up an episode, you stamp it "done" so you never redo
it. The logbook is the single source of truth for what still needs doing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    """Current time as an ISO-8601 string in UTC (e.g. 2026-09-10T17:30:45Z)."""
    return datetime.now(timezone.utc).isoformat()


class EpisodeStore:
    """A JSON-backed ledger of podcast episodes and their pipeline status.

    Example
    -------
    >>> store = EpisodeStore(Path("data/episodes.json"))
    >>> store.record_detection({"episode_id": "ep1", "title": "Hello",
    ...                         "show_name": "Show"}, progress_ms=1000,
    ...                        duration_ms=60000)
    >>> [e["episode_id"] for e in store.pending()]
    ['ep1']
    >>> store.mark_processed("ep1")
    >>> store.pending()
    []
    """

    def __init__(self, path: Path):
        self.path = path
        self._records: dict[str, dict] = {}
        self._load()

    # --- persistence -------------------------------------------------------
    def _load(self) -> None:
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as fh:
                self._records = json.load(fh)

    def _save(self) -> None:
        # Write to a temp file then rename: an atomic swap, so a crash or power
        # cut mid-write (very possible on a Pi) can never leave a half-written,
        # corrupt ledger — you either get the old file or the fully new one.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(self._records, fh, indent=2, ensure_ascii=False)
        tmp.replace(self.path)

    # --- recording ---------------------------------------------------------
    def record_detection(
        self,
        episode: dict[str, Any],
        *,
        progress_ms: int | None = None,
        duration_ms: int | None = None,
    ) -> bool:
        """Note that an episode was seen playing. Returns True if it's new.

        Called on every poll where an episode is playing. The first time we
        see an episode it's added with status "detected"; subsequent sightings
        just update the counters and how far you'd listened (the furthest
        progress we've observed), which later stages can use to decide whether
        you got far enough in to bother summarizing it.
        """
        episode_id = episode.get("episode_id")
        if not episode_id:
            # Defensive: without an ID we can't dedupe, so we skip it rather
            # than risk processing the same episode over and over.
            return False

        record = self._records.get(episode_id)
        is_new = record is None
        if record is None:
            record = {
                "episode_id": episode_id,
                "status": "detected",
                "first_detected": _now(),
                "times_seen": 0,
                "max_progress_ms": 0,
            }

        # Refresh the descriptive metadata each time (cheap, and it self-heals
        # if an earlier sighting had a partial record).
        for key in ("title", "show_name", "description", "release_date",
                    "spotify_url"):
            if episode.get(key) is not None:
                record[key] = episode[key]

        record["last_detected"] = _now()
        record["times_seen"] = record.get("times_seen", 0) + 1
        if duration_ms is not None:
            record["duration_ms"] = duration_ms
        if progress_ms is not None:
            record["max_progress_ms"] = max(
                record.get("max_progress_ms", 0), progress_ms
            )

        self._records[episode_id] = record
        self._save()
        return is_new

    def mark_processed(self, episode_id: str) -> None:
        """Stamp an episode as fully handled so it's never processed again."""
        record = self._records.get(episode_id, {"episode_id": episode_id})
        record["status"] = "processed"
        record["processed_at"] = _now()
        self._records[episode_id] = record
        self._save()

    # --- queries -----------------------------------------------------------
    def is_processed(self, episode_id: str) -> bool:
        rec = self._records.get(episode_id)
        return bool(rec and rec.get("status") == "processed")

    def pending(self) -> list[dict]:
        """Episodes seen playing but not yet processed — the pipeline's queue."""
        return [
            rec for rec in self._records.values()
            if rec.get("status") != "processed"
        ]

    def all(self) -> list[dict]:
        return list(self._records.values())
