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


# Some podcast CDNs (beehiiv, others) reject requests whose User-Agent isn't a
# recognizable browser or podcast app — returning 403 even for a public file.
# We identify as a mainstream client, and fall back to Apple's podcast-player
# UA, which podcast hosts almost universally allow. This is standard practice
# for downloading a public episode you already listen to.
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_PODCAST_APP_UA = (
    "AppleCoreMedia/1.0.0.19F77 (iPhone; U; CPU OS 15_5 like Mac OS X)"
)
_DOWNLOAD_USER_AGENTS = (_BROWSER_UA, _PODCAST_APP_UA, config.HTTP_USER_AGENT)


class AudioDownloadError(RuntimeError):
    """Raised when an audio URL can't be fetched (e.g. the host blocks us)."""


def download_audio(audio_url: str, dest_basename: str,
                   *, session: requests.Session | None = None) -> Path:
    """Stream an audio URL to <AUDIO_DIR>/<dest_basename><ext>. Returns the path.

    Streaming (chunk by chunk) matters: a 2-hour episode can be 100+ MB, and we
    don't want to hold the whole thing in memory — especially on the Pi.

    If the host refuses our client (401/403/406), we retry with a couple of
    alternative User-Agents before giving up with a clear error.
    """
    sess = session or requests.Session()
    config.AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    last_status: int | None = None
    for user_agent in _DOWNLOAD_USER_AGENTS:
        headers = {"User-Agent": user_agent, "Accept": "*/*"}
        try:
            # follow redirects (podcast hosts love tracking-prefix redirects)
            with sess.get(audio_url, stream=True, timeout=60,
                          allow_redirects=True, headers=headers) as r:
                if r.status_code in (401, 403, 406):
                    # Likely a client/User-Agent filter — try the next identity.
                    last_status = r.status_code
                    continue
                r.raise_for_status()
                ext = _extension_for(r.url, r.headers.get("Content-Type"))
                dest = config.AUDIO_DIR / f"{dest_basename}{ext}"
                tmp = dest.with_suffix(dest.suffix + ".part")
                with tmp.open("wb") as fh:
                    for chunk in r.iter_content(chunk_size=1 << 16):  # 64 KB
                        if chunk:
                            fh.write(chunk)
                tmp.replace(dest)  # atomic: a partial download never looks whole
                return dest
        except requests.RequestException as exc:
            raise AudioDownloadError(
                f"Network error downloading audio: {exc}"
            ) from exc

    raise AudioDownloadError(
        f"The host refused every client identity we tried "
        f"(last status {last_status}) for:\n  {audio_url}\n"
        "This usually means the CDN blocks automated downloads. Options: try "
        "again later, or find the direct file URL in your podcast app and pass "
        "it with --audio-url."
    )
