"""Find a podcast's public RSS feed from just its show name.

The problem this solves
-----------------------
Spotify tells us a show's *name* ("AI Report") but never where its audio
actually lives. Almost every podcast — even ones you listen to inside Spotify —
is really published as an open **RSS feed** on the show's own server, and
that's where the downloadable MP3 sits. We just have to find that feed.

The trick
---------
Apple runs a free, no-key-required search API (originally for iTunes) that,
given a show name, returns matching podcasts *including their RSS feed URL* in
a field called `feedUrl`. Apple has indexed practically every non-exclusive
podcast, so this is a reliable public directory to look things up in.

Everyday analogy: Spotify hands you a restaurant's *name*; Apple's directory is
the phone book you flip through to get its actual street address (the feed URL),
which is where you then go to collect the food (the audio).

Honesty note: a show name is not unique. "AI Report" could match several
podcasts. We pick the closest name match and always report which feed we chose,
so a wrong guess is easy to spot and override.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

import requests

from . import config

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.HTTP_USER_AGENT})
    return s


def _similarity(a: str, b: str) -> float:
    """0.0–1.0 score of how alike two strings are, case/space-insensitive.

    SequenceMatcher compares the sequences of characters; 1.0 is identical.
    We lowercase and trim first so "AI Report " and "ai report" score 1.0.
    """
    return SequenceMatcher(None, (a or "").lower().strip(),
                           (b or "").lower().strip()).ratio()


def search_podcasts(show_name: str, *, limit: int = 10,
                    session: requests.Session | None = None) -> list[dict[str, Any]]:
    """Query Apple's directory and return raw candidate podcast records."""
    sess = session or _session()
    resp = sess.get(
        ITUNES_SEARCH_URL,
        params={"media": "podcast", "term": show_name, "limit": limit},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def rank_candidates(show_name: str,
                    results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort candidates by how closely their name matches, best first.

    Each returned dict is trimmed to the bits we care about plus a `score`, so
    the caller (and the user) can see exactly why a feed was chosen.
    """
    ranked = []
    for r in results:
        feed_url = r.get("feedUrl")
        if not feed_url:
            continue  # No feed = useless to us (e.g. Spotify-exclusive shows).
        ranked.append({
            "show_name": r.get("collectionName"),
            "artist": r.get("artistName"),
            "feed_url": feed_url,
            "score": round(_similarity(show_name, r.get("collectionName", "")), 3),
        })
    ranked.sort(key=lambda c: c["score"], reverse=True)
    return ranked


def find_feed_url(show_name: str, *, min_score: float = 0.6,
                  session: requests.Session | None = None) -> dict[str, Any] | None:
    """Return the best-matching {show_name, artist, feed_url, score}, or None.

    Returns None when nothing clears `min_score`, rather than silently handing
    back a bad guess. The caller should show the candidate to the user.
    """
    ranked = rank_candidates(show_name, search_podcasts(show_name, session=session))
    if not ranked:
        return None
    best = ranked[0]
    return best if best["score"] >= min_score else None
