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

## 4. How the trigger actually works (and why not recently-played)

We tested it: Spotify's `recently-played` endpoint returns **only music
tracks — never podcast episodes** (still true in 2026). You can reconfirm this
any time with the diagnostic `python -m podcast_transcriber fetch --raw`.

So the live trigger instead polls the **"what's playing right now"** endpoint,
which *can* return episodes (we pass an explicit `additional_types=episode`
flag; without it, episodes are hidden — the same trap). This directly observes
what you actually listen to.

### Verify it detects episodes

1. On any device signed into the same Spotify account, **start playing a
   podcast episode** and leave it playing.
2. On the PC, run a single check:
   ```bash
   python -m podcast_transcriber poll
   ```
   You should see a line like
   `Episode playing [NEW]: <Show> — <Episode> (at ~N min)`.
3. Confirm it was recorded:
   ```bash
   python -m podcast_transcriber queue
   ```

If `poll` says "No episode playing" while an episode really is playing, tell
Claude — a couple of accounts need `additional_types` handled slightly
differently, and we'll adjust.

### The tradeoff to understand

"What's playing right now" is a *snapshot* — it only reports the instant you
ask. To turn snapshots into reliable history you must poll **often**. On the
always-on Pi that's a cron job every minute; on your PC for testing you can
loop in the foreground:

```bash
python -m podcast_transcriber poll --watch --interval 60   # Ctrl+C to stop
```

Everything downstream (fetch → transcribe → summarize → deliver) reads from the
same `data/episodes.json` queue and is unaffected by this choice.
