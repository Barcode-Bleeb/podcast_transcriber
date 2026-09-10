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

    python -m podcast_transcriber download
        Stage 2. Take the oldest queued episode, find the show's RSS feed,
        match the episode, and download its audio into audio/. Overrides:
        --id, --show, --feed-url, --audio-url, --yes.

    python -m podcast_transcriber transcribe
        Stage 3. Transcribe the oldest downloaded episode with local Whisper.
        Writes transcripts/<id>.txt (+ .segments.json). Slow but not
        time-sensitive. Overrides: --id, --model, --language.

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
from pathlib import Path

import json as _json

from . import audio_fetch, config, feed_finder, spotify_client, transcribe
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


def _pick_target(store: EpisodeStore, episode_id: str | None) -> dict | None:
    """Choose which episode to download: an explicit --id, else oldest pending
    that has no audio yet."""
    if episode_id:
        return store.get(episode_id)
    candidates = [
        e for e in store.pending() if not e.get("audio_path")
    ]
    candidates.sort(key=lambda e: e.get("first_detected", ""))
    return candidates[0] if candidates else None


def _cmd_download(args: argparse.Namespace) -> int:
    store = EpisodeStore(config.EPISODES_FILE)
    episode = _pick_target(store, args.id)
    if episode is None:
        print("Nothing to download (no pending episode without audio). "
              "Run `poll` while an episode plays, or pass --id.")
        return 1

    ep_id = episode["episode_id"]
    print(f"Target: {episode.get('show_name')} — {episode.get('title')}")

    # --- Step 1: find the RSS feed (unless one was given) ------------------
    feed_url = args.feed_url
    if not feed_url and not args.audio_url:
        show = args.show or episode.get("show_name") or ""
        print(f"Searching Apple's directory for feed of: {show!r}")
        results = feed_finder.rank_candidates(
            show, feed_finder.search_podcasts(show)
        )
        if not results:
            print("No feeds found. Try `--show \"Exact Show Name\"` or pass "
                  "`--feed-url <url>` directly.")
            return 1
        print("Top feed candidates (name-match score):")
        for c in results[:5]:
            print(f"  {c['score']:.2f}  {c['show_name']}  <{c['feed_url']}>")
        best = results[0]
        if best["score"] < 0.6 and not args.yes:
            print(f"\nBest match scored only {best['score']:.2f} — not confident.\n"
                  "If the top candidate above is right, re-run with --yes, or "
                  "pass --feed-url <url>.")
            return 1
        feed_url = best["feed_url"]
        print(f"Using feed: {feed_url}")

    # --- Step 2: match the episode within the feed ------------------------
    audio_url = args.audio_url
    if not audio_url:
        print("Parsing feed and matching the episode by title...")
        feed = audio_fetch.parse_feed(feed_url)
        if not feed.entries:
            print("Feed parsed but has no entries. Wrong feed? Try --feed-url.")
            return 1
        matches = audio_fetch.match_episode(feed, episode.get("title", ""))
        print("Best episode matches (title-match score):")
        for m in matches:
            print(f"  {m['score']:.2f}  {m['title']}")
        best = matches[0]
        if best["score"] < 0.5 and not args.yes:
            print(f"\nBest episode match scored only {best['score']:.2f} — not "
                  "confident. Re-run with --yes to accept it, or pass "
                  "--audio-url <url>.")
            return 1
        audio_url = best["audio_url"]
        if not audio_url:
            print("Matched an episode but it has no downloadable audio "
                  "enclosure. Pass --audio-url if you can find it manually.")
            return 1

    # --- Step 3: download -------------------------------------------------
    print(f"Downloading audio:\n  {audio_url}")
    try:
        dest = audio_fetch.download_audio(audio_url, dest_basename=ep_id)
    except audio_fetch.AudioDownloadError as exc:
        print(f"\nDownload failed.\n{exc}")
        return 1
    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"Saved {size_mb:.1f} MB -> {dest}")

    store.update(ep_id, feed_url=feed_url, audio_url=audio_url,
                 audio_path=str(dest))
    print("Ledger updated. Ready for Stage 3 (transcription).")
    return 0


def _fmt_hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _cmd_transcribe(args: argparse.Namespace) -> int:
    store = EpisodeStore(config.EPISODES_FILE)

    # Pick target: explicit --id, else oldest episode that has audio but no
    # transcript yet.
    if args.id:
        episode = store.get(args.id)
    else:
        todo = [e for e in store.pending()
                if e.get("audio_path") and not e.get("transcript_path")]
        todo.sort(key=lambda e: e.get("first_detected", ""))
        episode = todo[0] if todo else None

    if episode is None:
        print("Nothing to transcribe (need an episode with audio and no "
              "transcript). Run `download` first, or pass --id.")
        return 1

    audio_path = Path(episode.get("audio_path", ""))
    if not audio_path.exists():
        print(f"Audio file missing on disk: {audio_path}\nRe-run `download`.")
        return 1

    ep_id = episode["episode_id"]
    print(f"Transcribing: {episode.get('show_name')} — {episode.get('title')}")
    print(f"Backend={config.WHISPER_BACKEND}  model={args.model or config.WHISPER_MODEL}"
          f"  (this can take many minutes; progress below)")

    # Live progress: overwrite one line so the terminal stays tidy.
    last = {"pct": -1}

    def _progress(done: float, total: float) -> None:
        pct = int(done / total * 100) if total else 0
        if pct != last["pct"]:
            last["pct"] = pct
            print(f"\r  {pct:3d}%  ({_fmt_hms(done)} / {_fmt_hms(total)})",
                  end="", flush=True)

    try:
        result = transcribe.transcribe_file(
            audio_path, model=args.model, language=args.language,
            progress=_progress,
        )
    except (RuntimeError, NotImplementedError, ValueError) as exc:
        print(f"\nTranscription failed.\n{exc}")
        return 1
    print()  # end the progress line

    config.TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    txt_path = config.TRANSCRIPTS_DIR / f"{ep_id}.txt"
    seg_path = config.TRANSCRIPTS_DIR / f"{ep_id}.segments.json"
    txt_path.write_text(result.text, encoding="utf-8")
    seg_path.write_text(
        _json.dumps([s.__dict__ for s in result.segments],
                    indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    words = len(result.text.split())
    print(f"Detected language: {result.language}   words: {words}")
    print(f"Transcript -> {txt_path}")
    store.update(ep_id, transcript_path=str(txt_path),
                 transcript_segments_path=str(seg_path),
                 language=result.language)
    print("Ledger updated. Ready for Stage 4 (summarize).")
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

    p_dl = sub.add_parser("download", help="Find RSS feed + download episode audio.")
    p_dl.add_argument("--id", help="Episode ID to download (default: oldest pending).")
    p_dl.add_argument("--show", help="Override the show name used for feed search.")
    p_dl.add_argument("--feed-url", dest="feed_url",
                      help="Skip discovery; use this RSS feed URL directly.")
    p_dl.add_argument("--audio-url", dest="audio_url",
                      help="Skip matching; download this audio URL directly.")
    p_dl.add_argument("--yes", action="store_true",
                      help="Accept the best match even if confidence is low.")
    p_dl.set_defaults(func=_cmd_download)

    p_tr = sub.add_parser("transcribe", help="Transcribe a downloaded episode.")
    p_tr.add_argument("--id", help="Episode ID (default: oldest with audio, no transcript).")
    p_tr.add_argument("--model", help="Whisper model size override (e.g. small, medium).")
    p_tr.add_argument("--language", help="Force language code (e.g. nl); default auto-detect.")
    p_tr.set_defaults(func=_cmd_transcribe)

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
