# Spotify setup — one-time walkthrough

This is the only part of Stage 1 that needs *you* (it can't be automated,
because you have to log in as yourself and click "Agree"). It takes ~5 minutes
and you never have to repeat it.

---

## 1. Create a Spotify Developer app

An "app" here is just a set of API keys tied to your Spotify account. It does
**not** get published anywhere and no one else sees it.

1. Go to <https://developer.spotify.com/dashboard> and log in with your normal
   Spotify account.
2. Click **Create app**.
3. Fill in:
   - **App name**: anything, e.g. `podcast-transcriber`
   - **App description**: anything, e.g. `personal podcast pipeline`
   - **Redirect URI**: `http://127.0.0.1:8888/callback`
     - ⚠️ This must match *exactly* what's in your `.env`. Use `127.0.0.1`,
       **not** `localhost` — Spotify now rejects `localhost`.
     - Click **Add** so it appears in the list below the box.
   - **Which API/SDKs are you planning to use?**: tick **Web API**.
4. Agree to the terms and click **Save**.

## 2. Copy your keys into `.env`

1. Open your new app, go to **Settings**.
2. You'll see **Client ID**. Copy it.
3. Click **View client secret** and copy that too.
4. In the project folder:
   ```bash
   cp .env.example .env
   ```
   Then edit `.env` and paste in your `SPOTIFY_CLIENT_ID` and
   `SPOTIFY_CLIENT_SECRET`. Leave the redirect URI as-is.

> Think of the **Client ID** as your app's username and the **Client Secret**
> as its password. The secret is sensitive — the `.env` file is git-ignored so
> it never leaves your machine.

## 3. Install dependencies and authorize

```bash
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt

python -m podcast_transcriber authorize
```

`authorize` will print a URL. Open it in a browser, log in, and click
**Agree**. Spotify then redirects you to a URL starting with
`http://127.0.0.1:8888/callback?code=...`. Your browser will show a
"can't connect" page — **that's expected** (nothing is listening on that
port). Copy the **full URL** from the address bar and paste it back into the
terminal when prompted.

That writes a cached token to `data/.spotify_token_cache.json`. From now on the
pipeline refreshes the token automatically and never needs the browser again.

### Doing this on a headless Raspberry Pi

Same command over SSH. The URL is printed to the terminal, you open it in a
browser on *any* device, and paste the redirected URL back into the SSH
session. No graphical browser on the Pi is required.

---

## 4. The big question: does recently-played even include episodes?

⚠️ **Please read this before we build the rest of the pipeline.**

Spotify's `recently-played` endpoint has, for years, returned **only music
tracks — not podcast episodes**. Whether that is still true in 2026 is
something I could not verify with certainty, so we test it directly:

```bash
python -m podcast_transcriber fetch --raw
```

- If it lists your recent podcast episodes: 🎉 the plan works as designed.
- If it says "No podcast EPISODES found": open the newest file in `data/raw/`
  and check the `track.type` values. If they're all `"track"`, the limitation
  still holds and we need a **fallback trigger**. Options we can discuss:
  - **`user-read-playback-state` / currently-playing polling** — catch episodes
    while they play (needs the pipeline running frequently).
  - **A "podcasts I follow / saved episodes" poll** — trigger on newly
    available episodes of shows you follow, rather than on listen history.
  - **A manual trigger** — you drop an episode URL/ID into a watched file.

Either way, everything downstream (fetch → transcribe → summarize → deliver)
is unchanged; only *how we notice an episode* would adapt. That's exactly why
we validated this foundation first.
