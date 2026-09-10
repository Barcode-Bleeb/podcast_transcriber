"""Central configuration for the podcast pipeline.

Everything that might change between your PC and the Raspberry Pi — or that is
secret — is read from environment variables (loaded from a local .env file).
This keeps secrets out of the code and makes the Pi deployment a matter of
copying one .env file across.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load variables from a .env file sitting at the project root, if present.
# On the Pi you might instead set real environment variables; either works.
load_dotenv()

# --- Paths -----------------------------------------------------------------
# PROJECT_ROOT is two parents up from this file:
#   src/podcast_transcriber/config.py  ->  <root>
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

# Where spotipy caches the OAuth token (access + refresh token). Deleting this
# file forces a fresh browser authorization next run.
SPOTIFY_TOKEN_CACHE = DATA_DIR / ".spotify_token_cache.json"

# Our own record of every podcast episode we've noticed playing, and how far
# each one has progressed through the pipeline. One file, keyed by episode ID,
# acts as both the "to-do queue" (status: detected) and the "already handled"
# ledger (status: processed), so nothing is missed or done twice.
EPISODES_FILE = DATA_DIR / "episodes.json"

# Where raw API dumps land when you run the fetcher in --raw mode. Handy for
# inspecting exactly what Spotify returns for your account.
RAW_DUMP_DIR = DATA_DIR / "raw"


# --- Spotify credentials ---------------------------------------------------
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_REDIRECT_URI = os.getenv(
    "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"
)

# The permission we ask the user to grant. We poll the "what's playing right
# now" endpoint to catch podcast episodes as they play, so we need the
# currently-playing scope. (We started with user-read-recently-played, but that
# endpoint returns only music tracks — never podcast episodes — so we switched.)
#
# NOTE: changing this scope invalidates the previously cached token, so the
# next `authorize` run will (correctly) prompt for the browser step once more.
SPOTIFY_SCOPE = "user-read-currently-playing"


def ensure_data_dirs() -> None:
    """Create the local data directories if they do not exist yet."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DUMP_DIR.mkdir(parents=True, exist_ok=True)


def require_credentials() -> None:
    """Fail early and clearly if the Spotify keys are missing.

    Raising here (rather than letting spotipy throw a cryptic error later)
    means a first-time user gets a message that actually tells them what to do.
    """
    missing = [
        name
        for name, value in (
            ("SPOTIFY_CLIENT_ID", SPOTIFY_CLIENT_ID),
            ("SPOTIFY_CLIENT_SECRET", SPOTIFY_CLIENT_SECRET),
        )
        if not value
    ]
    if missing:
        raise SystemExit(
            "Missing Spotify credentials: "
            + ", ".join(missing)
            + "\n\nCreate a .env file (copy .env.example) and fill in the "
            "values from your Spotify Developer app.\n"
            "See docs/spotify-setup.md for the step-by-step guide."
        )
