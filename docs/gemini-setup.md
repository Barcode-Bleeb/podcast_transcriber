# Gemini setup — free summarization key

Stage 4 (summarize) uses Google's Gemini API. The **free tier** needs no
billing or credit card — just a Google account.

## 1. Get a free API key

1. Go to <https://aistudio.google.com/apikey> and sign in with a Google account.
2. Click **Create API key** (you can let it create a new project for you).
3. Copy the key.

## 2. Put it in your `.env`

Open your `.env` and set:

```
GEMINI_API_KEY=paste_your_key_here
```

That's it — the key is git-ignored, so it stays on your machine.

## 3. Install the Gemini library and run

```bash
pip install -e ".[summarize]"
python -m podcast_transcriber summarize
```

This reads the oldest transcribed episode, sends the transcript to Gemini, and
writes `summaries/<id>.json` and a styled `summaries/<id>.pdf`.

## Things to know (honestly)

- **Free-tier rate limits.** Google caps requests per minute and per day on the
  free tier. That's fine for a handful of episodes a day; it is not for bulk
  back-catalogue runs. If you hit a limit, wait and re-run — the episode stays
  queued.
- **Free-tier privacy.** On the free tier, Google may use your inputs to improve
  their products. Podcast transcripts aren't private data, but you should know
  the transcript text leaves your machine for this step (unlike transcription,
  which is fully local).
- **Model name drift.** The default is `GEMINI_MODEL=gemini-3.6-flash`. Free-tier
  model names change over time; if you get a 404 "model not found" error, the
  message usually names the replacement — set it in `.env` (or pass
  `--model <name>`). The AI Studio site also lists what your key can use.
- **Language.** Summaries are written in the podcast's own language (Dutch stays
  Dutch), so quotes remain the speakers' actual words.
- **Swappable.** The backend is pluggable (`SUMMARY_BACKEND`). We can add a paid
  Claude backend (best quality, ~cents/episode) or a local Ollama backend
  (fully offline) later without changing the rest of the pipeline.
