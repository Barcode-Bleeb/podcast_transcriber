# Automated Podcast Transcriber + Summarizer

A semi-automatic pipeline that detects podcast episodes you've listened to on
Spotify, transcribes them locally with Whisper, summarizes them in your format,
and delivers the result via email and Notion.

Built and tested on a PC first; eventual home is an always-on Raspberry Pi 5.

## Pipeline stages

| # | Stage | Status |
|---|-------|--------|
| 1 | **Trigger** — poll Spotify *now-playing* for episodes, queue + dedupe | 🟢 working (this checkpoint) |
| 2 | **Fetch** — find the show's RSS feed, download the audio | 🟢 built (verify on your machine) |
| 3 | **Transcribe** — local Whisper (`small`), pluggable backend | 🟢 built (verify on your machine) |
| 4 | **Summarize** — 3-section format → PDF | ⚪ not started |
| 5 | **Deliver** — email PDF + create Notion page | ⚪ not started |

## Stage 1 quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # then paste in your Spotify keys

python -m podcast_transcriber authorize                 # one-time, interactive
python -m podcast_transcriber poll                       # record what's playing now
python -m podcast_transcriber poll --watch --interval 60 # loop (Ctrl+C to stop)
python -m podcast_transcriber queue                      # show the backlog
```

The trigger polls Spotify's **now-playing** endpoint, because recently-played
returns only music, never podcast episodes. On the Pi this runs as a
per-minute cron job; episodes land in `data/episodes.json`, deduped.

Full click-by-click Spotify instructions are in
[`docs/spotify-setup.md`](docs/spotify-setup.md).

## Stage 2 — download an episode's audio

```bash
python -m podcast_transcriber download            # oldest queued episode
```

Spotify never exposes the real audio file, so this looks the show up in
Apple's free podcast directory to find its public **RSS feed**, matches the
episode by title, and streams the MP3 into `audio/`. It prints its confidence
at each step so you can catch a wrong guess. Overrides when a name is ambiguous:

```bash
python -m podcast_transcriber download --show "Exact Show Name"
python -m podcast_transcriber download --feed-url https://…/feed.xml
python -m podcast_transcriber download --audio-url https://…/episode.mp3
python -m podcast_transcriber download --yes        # accept a low-confidence match
```

## Stage 3 — transcribe locally with Whisper

Transcription engines are heavy, so they're an optional install:

```bash
pip install -e ".[whisper]"                     # adds faster-whisper (PC)
python -m podcast_transcriber transcribe         # oldest downloaded episode
```

Writes `transcripts/<id>.txt` plus `<id>.segments.json` (timestamped chunks,
handy for pulling quotes in Stage 4). It's CPU-bound and slow by design
(minutes to tens of minutes) — the free/overnight tradeoff. The backend is
pluggable via `WHISPER_BACKEND`: `faster-whisper` on a PC now, `whisper.cpp` on
the Pi later. Model, device, compute type and language are env-tunable
(`WHISPER_MODEL`, `WHISPER_LANGUAGE=nl`, …).

## Layout

```
src/podcast_transcriber/
  config.py           # paths + secrets from environment / .env
  spotify_client.py   # OAuth handshake + now-playing episode detection
  store.py            # JSON episode ledger (queue + processed, deduped)
  feed_finder.py      # show name -> RSS feed via Apple's directory
  audio_fetch.py      # parse feed, match episode, download audio
  transcribe.py       # pluggable Whisper backend (faster-whisper / whisper.cpp)
  __main__.py         # `python -m podcast_transcriber ...` CLI
data/                 # local runtime data (git-ignored: tokens, ledger, dumps)
docs/                 # setup guides
```

## Design decisions already locked in

- **Local Whisper** (`whisper.cpp`, `small` model) over an API — free, and
  speed isn't a concern given overnight processing.
- **Notion** over Obsidian for the note destination.
- Spotify's ~50-item recently-played cap, and its inability to tell "finished"
  from "briefly played", are accepted tradeoffs.
- Apple Podcasts is out of scope for triggering (no public listening-history
  API).
