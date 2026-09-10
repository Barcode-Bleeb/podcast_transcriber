"""Spotify authorization and recently-played fetching.

This module does two jobs:

1. Handle the one-time OAuth "handshake" so we can talk to Spotify on your
   behalf, and transparently refresh the token forever after.
2. Fetch your recently-played items and normalize the podcast episodes into a
   simple, pipeline-friendly shape.

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
# Fetching + normalizing recently-played items
# --------------------------------------------------------------------------

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
