# Automated Podcast Transcriber + Summarizer

A semi-automatic pipeline that detects podcast episodes you've listened to on
Spotify, transcribes them locally with Whisper, summarizes them in your format,
and delivers the result via email and Notion.

Built and tested on a PC first; eventual home is an always-on Raspberry Pi 5.

## Pipeline stages

| # | Stage | Status |
|---|-------|--------|
| 1 | **Trigger** — poll Spotify recently-played, filter episodes, dedupe | 🟢 in progress (this checkpoint) |
| 2 | **Fetch** — find the show's RSS feed, download the audio | ⚪ not started |
| 3 | **Transcribe** — local `whisper.cpp`, `small` model | ⚪ not started |
| 4 | **Summarize** — 3-section format → PDF | ⚪ not started |
| 5 | **Deliver** — email PDF + create Notion page | ⚪ not started |

## Stage 1 quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # then paste in your Spotify keys

python -m podcast_transcriber authorize        # one-time, interactive
python -m podcast_transcriber fetch --raw       # list new episodes + dump raw
```

Full click-by-click Spotify instructions — including creating the developer
app and an important caveat about whether episodes appear at all — are in
[`docs/spotify-setup.md`](docs/spotify-setup.md).

## Layout

```
src/podcast_transcriber/
  config.py           # paths + secrets from environment / .env
  spotify_client.py   # OAuth handshake + recently-played fetching
  store.py            # JSON ledger of already-processed episode IDs
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
