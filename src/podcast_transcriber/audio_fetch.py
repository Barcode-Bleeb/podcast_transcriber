"""Given a feed URL and an episode title, find and download the audio file.

Three steps:
  1. Parse the RSS feed (feedparser turns the XML into a list of entries).
  2. Match the Spotify episode title to a feed entry. Titles rarely match
     character-for-character between Spotify and the raw feed, so we compare by
     similarity and pick the closest — always reporting the score so a bad
     match is visible.
  3. Pull the audio URL out of the entry's <enclosure> (the standard RSS tag
     that points at the actual media file) and stream it to disk.

Everyday analogy for step 3: an <enclosure> is the feed saying "here is the
attachment for this episode", exactly like a file attached to an email. We just
follow that link and save the attachment.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import feedparser
import requests

from . import config


def _norm(text: str) -> str:
    """Lowercase, collapse whitespace — so trivial differences don't hurt matching."""
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def parse_feed(feed_url: str) -> feedparser.FeedParserDict:
    """Download and parse an RSS feed into structured entries."""
    # feedparser fetches the URL itself; we pass our User-Agent so hosts that
    # block generic clients still serve us.
    return feedparser.parse(feed_url, agent=config.HTTP_USER_AGENT)


def match_episode(feed: feedparser.FeedParserDict, episode_title: str,
                  *, top_n: int = 3) -> list[dict[str, Any]]:
    """Return the best-matching feed entries for a title, closest first.

    We return a short ranked list (not just the winner) so the caller can show
    alternatives if the top match looks wrong.
    """
    target = _norm(episode_title)
    scored = []
    for entry in feed.entries:
        title = entry.get("title", "")
        score = SequenceMatcher(None, target, _norm(title)).ratio()
        scored.append({
            "title": title,
            "score": round(score, 3),
            "audio_url": _enclosure_url(entry),
            "published": entry.get("published", ""),
            "summary": entry.get("summary", ""),
        })
    scored.sort(key=lambda e: e["score"], reverse=True)
    return scored[:top_n]


def _enclosure_url(entry: dict[str, Any]) -> str | None:
    """Extract the audio file URL from a feed entry's enclosure(s)."""
    # feedparser exposes enclosures in entry.enclosures / entry.links with
    # rel == "enclosure". Prefer an explicitly audio-typed one.
    for link in entry.get("links", []):
        if link.get("rel") == "enclosure":
            href = link.get("href")
            if link.get("type", "").startswith("audio") or href:
                return href
    encs = entry.get("enclosures", [])
    if encs:
        return encs[0].get("href") or encs[0].get("url")
    return None


def _extension_for(url: str, content_type: str | None) -> str:
    """Best-guess file extension from the URL or the server's content type."""
    m = re.search(r"\.(mp3|m4a|aac|ogg|wav|mp4)(?:\?|$)", url, re.IGNORECASE)
    if m:
        return "." + m.group(1).lower()
    if content_type:
        if "mpeg" in content_type or "mp3" in content_type:
            return ".mp3"
        if "mp4" in content_type or "m4a" in content_type or "aac" in content_type:
            return ".m4a"
    return ".mp3"  # A safe, common default; whisper.cpp handles it via ffmpeg.


def download_audio(audio_url: str, dest_basename: str,
                   *, session: requests.Session | None = None) -> Path:
    """Stream an audio URL to data-dir/audio/<dest_basename><ext>. Returns the path.

    Streaming (chunk by chunk) matters: a 2-hour episode can be 100+ MB, and we
    don't want to hold the whole thing in memory — especially on the Pi.
    """
    sess = session or requests.Session()
    sess.headers.setdefault("User-Agent", config.HTTP_USER_AGENT)

    config.AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    # follow redirects (podcast hosts love tracking-prefix redirects)
    with sess.get(audio_url, stream=True, timeout=60, allow_redirects=True) as r:
        r.raise_for_status()
        ext = _extension_for(r.url, r.headers.get("Content-Type"))
        dest = config.AUDIO_DIR / f"{dest_basename}{ext}"
        tmp = dest.with_suffix(dest.suffix + ".part")
        with tmp.open("wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 16):  # 64 KB chunks
                if chunk:
                    fh.write(chunk)
        tmp.replace(dest)  # atomic: a partial download never looks complete
    return dest
