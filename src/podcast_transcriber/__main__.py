"""Command-line entry point for Stage 1 (Spotify trigger).

Run everything from the project root.

    python -m podcast_transcriber authorize
        One-time browser authorization. Run this first, interactively.
        (Re-run it whenever the required permissions change.)

    python -m podcast_transcriber poll
        THE MAIN COMMAND. Check what's playing right now; if it's a podcast
        episode, record it to the queue (data/episodes.json). Run once and
        exit — ideal for a cron job that fires every minute on the Pi.

    python -m podcast_transcriber poll --watch --interval 60
        Same, but keep looping in the foreground, polling every 60 seconds.
        Handy for testing on your PC (press Ctrl+C to stop).

    python -m podcast_transcriber queue
        Show episodes detected but not yet processed (the pipeline's backlog).

    python -m podcast_transcriber fetch --raw
        DIAGNOSTIC ONLY. Dump recently-played to prove auth works and to
        re-check whether Spotify ever starts including episodes there (it
        currently does not).
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

from . import config, spotify_client
from .store import EpisodeStore


def _cmd_authorize(_args: argparse.Namespace) -> int:
    spotify_client.authorize()
    return 0


def _poll_once(store: EpisodeStore, *, verbose: bool = True) -> bool:
    """Do one 'what's playing?' check. Returns True if an episode was recorded."""
    response = spotify_client.fetch_now_playing()
    episode, progress_ms = spotify_client.now_playing_episode(response)

    if episode is None:
        if verbose:
            what = "nothing" if not response else response.get(
                "currently_playing_type", "unknown"
            )
            print(f"[{_stamp()}] No episode playing (currently: {what}).")
        return False

    is_new = store.record_detection(
        episode,
        progress_ms=progress_ms,
        duration_ms=episode.get("duration_ms"),
    )
    tag = "NEW" if is_new else "seen again"
    mins = (progress_ms or 0) // 60000
    print(
        f"[{_stamp()}] Episode playing [{tag}]: "
        f"{episode['show_name']} — {episode['title']} "
        f"(at ~{mins} min)"
    )
    return True


def _cmd_poll(args: argparse.Namespace) -> int:
    store = EpisodeStore(config.EPISODES_FILE)

    if not args.watch:
        _poll_once(store)
        return 0

    print(
        f"Watching now-playing every {args.interval}s. Press Ctrl+C to stop."
    )
    try:
        while True:
            _poll_once(store)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


def _cmd_queue(_args: argparse.Namespace) -> int:
    store = EpisodeStore(config.EPISODES_FILE)
    pending = store.pending()
    print(f"Episodes waiting to be processed: {len(pending)}")
    for ep in pending:
        print(f"  - {ep.get('show_name')} — {ep.get('title')}")
        print(
            f"      id={ep.get('episode_id')}  "
            f"seen {ep.get('times_seen', 0)}x  "
            f"first={ep.get('first_detected')}"
        )
    return 0


def _cmd_fetch(args: argparse.Namespace) -> int:
    items = spotify_client.fetch_recently_played(limit=args.limit)
    print(f"Spotify returned {len(items)} recently-played item(s).")

    if args.raw:
        config.ensure_data_dirs()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = config.RAW_DUMP_DIR / f"recently_played_{stamp}.json"
        with out.open("w", encoding="utf-8") as fh:
            json.dump(items, fh, indent=2, ensure_ascii=False)
        print(f"Raw API items dumped to: {out}")

    episodes = spotify_client.extract_episodes(items)
    if episodes:
        print(f"\nFound {len(episodes)} podcast episode(s) in recently-played:")
        for ep in episodes:
            print(f"  - {ep['show_name']} — {ep['title']}")
        print(
            "\nInteresting — Spotify used to omit episodes here. Worth telling "
            "Claude; the trigger could be simplified if this is reliable."
        )
    else:
        print(
            "\nNo podcast EPISODES in recently-played (only music), as "
            "expected. This is a diagnostic; the live trigger is `poll`."
        )
    return 0


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="podcast_transcriber",
        description="Stage 1: Spotify now-playing trigger.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_auth = sub.add_parser("authorize", help="One-time browser authorization.")
    p_auth.set_defaults(func=_cmd_authorize)

    p_poll = sub.add_parser("poll", help="Check now-playing; record episodes.")
    p_poll.add_argument(
        "--watch", action="store_true",
        help="Keep looping instead of checking once and exiting.",
    )
    p_poll.add_argument(
        "--interval", type=int, default=60,
        help="Seconds between checks when --watch is set (default 60).",
    )
    p_poll.set_defaults(func=_cmd_poll)

    p_queue = sub.add_parser("queue", help="List episodes awaiting processing.")
    p_queue.set_defaults(func=_cmd_queue)

    p_fetch = sub.add_parser("fetch", help="Diagnostic: dump recently-played.")
    p_fetch.add_argument("--limit", type=int, default=50,
                         help="How many recent items to request (max 50).")
    p_fetch.add_argument("--raw", action="store_true",
                         help="Also dump the untouched API response to data/raw/.")
    p_fetch.set_defaults(func=_cmd_fetch)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
