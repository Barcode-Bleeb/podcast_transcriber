"""Spotify authorization and episode detection.

This module does two jobs:

1. Handle the one-time OAuth "handshake" so we can talk to Spotify on your
   behalf, and transparently refresh the token forever after.
2. Poll the "what's playing right now" endpoint to catch podcast episodes as
   you listen, and normalize them into a simple, pipeline-friendly shape.
   (A recently-played helper remains as a diagnostic only — that endpoint was
   confirmed to return music tracks but never podcast episodes.)

--------------------------------------------------------------------------
A note on OAuth, in everyday terms
--------------------------------------------------------------------------
Think of OAuth like a hotel key card. You (the guest) prove who you are at the
front desk ONCE, in person. The desk then hands you a key card that opens only
your room, for a limited time. You never hand out your master identity again;
you just tap the card. If the card expires, the desk quietly issues a new one
because it already trusts you.

- Logging in on Spotify's website  = proving who you are at the front desk.
- The "access token"               = the key card (expires after ~1 hour).
- The "refresh token"              = the desk's standing permission to reissue
                                     your card without you showing up again.

spotipy stores both tokens in a cache file (data/.spotify_token_cache.json).
That is why you only ever have to click "Agree" in the browser once.
"""

from __future__ import annotations

from typing import Any

import spotipy
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyOAuth

from . import config


def build_auth_manager() -> SpotifyOAuth:
    """Create the object that manages tokens (getting, caching, refreshing)."""
    config.require_credentials()
    config.ensure_data_dirs()

    return SpotifyOAuth(
        client_id=config.SPOTIFY_CLIENT_ID,
        client_secret=config.SPOTIFY_CLIENT_SECRET,
        redirect_uri=config.SPOTIFY_REDIRECT_URI,
        scope=config.SPOTIFY_SCOPE,
        cache_handler=CacheFileHandler(
            cache_path=str(config.SPOTIFY_TOKEN_CACHE)
        ),
        # We manage the browser step ourselves (works on a headless Pi over
        # SSH): spotipy prints the authorize URL and waits for you to paste
        # back the URL you were redirected to.
        open_browser=False,
    )


def get_client() -> spotipy.Spotify:
    """Return an authenticated Spotify client, ready to make API calls.

    If no valid cached token exists, spotipy will kick off the interactive
    browser authorization the first time a call needs a token.
    """
    return spotipy.Spotify(auth_manager=build_auth_manager())


def authorize() -> None:
    """Force the one-time authorization now, so cron runs never block on it.

    Run this once, interactively, before you schedule anything. It performs a
    trivial API call which triggers the token handshake and writes the cache.
    """
    client = get_client()
    me = client.current_user()
    display = me.get("display_name") or me.get("id", "unknown")
    print(f"Authorized successfully as: {display}")
    print(f"Token cached at: {config.SPOTIFY_TOKEN_CACHE}")


# --------------------------------------------------------------------------
# Now playing — the PRIMARY trigger
# --------------------------------------------------------------------------
# Spotify's "what's playing right now" endpoint CAN return podcast episodes,
# but only if we explicitly ask by passing additional_types="episode". Without
# that flag it silently reports only music — the same trap that makes
# recently-played useless for us. We always pass it.

def _episode_from_item(item: dict[str, Any]) -> dict[str, Any]:
    """Shape a raw Spotify episode object into our tidy record."""
    show = item.get("show") or {}
    return {
        "episode_id": item.get("id"),
        "title": item.get("name"),
        "show_name": show.get("name"),
        "description": item.get("description", ""),
        "duration_ms": item.get("duration_ms"),
        "release_date": item.get("release_date"),
        "spotify_url": (item.get("external_urls") or {}).get("spotify"),
    }


def fetch_now_playing() -> dict[str, Any] | None:
    """Return the raw currently-playing response, or None if nothing plays.

    The endpoint returns HTTP 204 (no content) when nothing is playing, which
    spotipy surfaces as None — so a None here simply means 'silence right now'.
    """
    client = get_client()
    return client.currently_playing(additional_types="episode")


def now_playing_episode(
    response: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, int | None]:
    """Extract the playing episode (and playback progress) from a response.

    Returns (episode_record, progress_ms). Both are None when what's playing
    isn't a podcast episode — e.g. music, an ad, or nothing at all — which lets
    the caller skip with a simple truthiness check.
    """
    if not response:
        return None, None
    if response.get("currently_playing_type") != "episode":
        return None, None
    item = response.get("item") or {}
    if not item.get("id"):
        return None, None
    return _episode_from_item(item), response.get("progress_ms")


# --------------------------------------------------------------------------
# Recently-played — kept only as a diagnostic
# --------------------------------------------------------------------------
# We confirmed empirically that this endpoint returns only music tracks for
# real accounts, so it is NOT part of the live trigger. It stays because
# `fetch` is a handy way to prove authorization works and to re-check whether
# Spotify ever starts including episodes here.

def fetch_recently_played(limit: int = 50) -> list[dict[str, Any]]:
    """Return the raw 'items' list from Spotify's recently-played endpoint.

    Spotify caps this at the 50 most recent items and does NOT tell us whether
    something was finished or merely started — a documented tradeoff we accept.
    """
    client = get_client()
    response = client.current_user_recently_played(limit=limit)
    return response.get("items", [])


def normalize_episode(item: dict[str, Any]) -> dict[str, Any] | None:
    """Turn one recently-played item into a tidy episode record, or None.

    Returns None for anything that is not a podcast episode (e.g. music
    tracks), which lets the caller filter with a simple list comprehension.

    IMPORTANT / HONEST CAVEAT: it is not yet confirmed that Spotify's
    recently-played endpoint returns podcast episodes at all — historically it
    returned only music tracks. This function is written defensively so that
    IF episodes appear, we capture them; run the fetcher with --raw to see the
    truth for your account. See docs/spotify-setup.md.
    """
    played_obj = item.get("track") or {}
    if played_obj.get("type") != "episode":
        return None

    show = played_obj.get("show") or {}
    return {
        "episode_id": played_obj.get("id"),
        "title": played_obj.get("name"),
        "show_name": show.get("name"),
        "description": played_obj.get("description", ""),
        "duration_ms": played_obj.get("duration_ms"),
        "release_date": played_obj.get("release_date"),
        "played_at": item.get("played_at"),
        "spotify_url": (played_obj.get("external_urls") or {}).get("spotify"),
    }


def extract_episodes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter a raw items list down to just the normalized podcast episodes."""
    episodes = (normalize_episode(item) for item in items)
    return [ep for ep in episodes if ep is not None]
