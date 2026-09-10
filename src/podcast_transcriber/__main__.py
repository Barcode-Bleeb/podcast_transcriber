"""Command-line entry point for Stage 1.

Usage (run from the project root):

    python -m podcast_transcriber authorize
        One-time browser authorization. Run this first, interactively.

    python -m podcast_transcriber fetch
        Fetch recently-played, show NEW podcast episodes (not yet processed).

    python -m podcast_transcriber fetch --raw
        Same, but also dump the untouched API response to data/raw/ so you can
        inspect exactly what Spotify returns for your account. Use this to
        settle the "does recently-played even include episodes?" question.

    python -m podcast_transcriber fetch --all
        Show every episode found, including ones already processed.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from . import config, spotify_client
from .store import ProcessedStore


def _cmd_authorize(_args: argparse.Namespace) -> int:
    spotify_client.authorize()
    return 0


def _dump_raw(items: list) -> None:
    config.ensure_data_dirs()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = config.RAW_DUMP_DIR / f"recently_played_{stamp}.json"
    with out.open("w", encoding="utf-8") as fh:
        json.dump(items, fh, indent=2, ensure_ascii=False)
    print(f"Raw API items dumped to: {out}")


def _cmd_fetch(args: argparse.Namespace) -> int:
    items = spotify_client.fetch_recently_played(limit=args.limit)
    print(f"Spotify returned {len(items)} recently-played item(s).")

    if args.raw:
        _dump_raw(items)

    episodes = spotify_client.extract_episodes(items)

    # Honest, actionable feedback about the big unknown in this stage.
    if not episodes:
        n_tracks = len(items)
        print(
            "\nNo podcast EPISODES found in the recently-played response.\n"
            f"({n_tracks} item(s) came back, but none had type 'episode'.)\n\n"
            "This may confirm the known limitation that Spotify's "
            "recently-played endpoint returns only music tracks. Run with "
            "--raw and inspect the dump to be sure, then let's discuss the "
            "fallback options (see docs/spotify-setup.md)."
        )
        return 0

    store = ProcessedStore(config.PROCESSED_EPISODES_FILE)

    if args.all:
        to_show = episodes
        header = "All podcast episodes in recently-played"
    else:
        to_show = [e for e in episodes if not store.is_processed(e["episode_id"])]
        header = "NEW podcast episodes (not yet processed)"

    print(f"\n{header}: {len(to_show)}")
    for ep in to_show:
        state = "done" if store.is_processed(ep["episode_id"]) else "new"
        print(f"  [{state}] {ep['show_name']} — {ep['title']}")
        print(f"         id={ep['episode_id']}  played_at={ep['played_at']}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="podcast_transcriber",
        description="Stage 1: Spotify recently-played trigger.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_auth = sub.add_parser("authorize", help="One-time browser authorization.")
    p_auth.set_defaults(func=_cmd_authorize)

    p_fetch = sub.add_parser("fetch", help="Fetch recently-played episodes.")
    p_fetch.add_argument(
        "--limit", type=int, default=50,
        help="How many recent items to request (max 50).",
    )
    p_fetch.add_argument(
        "--raw", action="store_true",
        help="Also dump the untouched API response to data/raw/.",
    )
    p_fetch.add_argument(
        "--all", action="store_true",
        help="Show every episode, including already-processed ones.",
    )
    p_fetch.set_defaults(func=_cmd_fetch)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
