"""Turn a transcript into a structured 3-section summary (Stage 4).

This is the "brain" step: it feeds the full transcript to a language model with
a careful prompt, and gets back a structured summary matching your established
format:

  PART 1 - Episode summary  : ~8-12 topic sections, 600-900 words total
  PART 2 - Key insights/quotes : 10-15 items, each with a short explanation
  PART 3 - Books & resources   : title + author + description

Design mirrors the transcriber: one function, `summarize_transcript()`, hides
which model did the work behind a pluggable backend. Right now that's Google
**Gemini** (free tier). "claude" and "ollama" backends are reserved for later.

We ask the model for **JSON** (not prose) so the PDF renderer can lay out each
piece precisely — the model writes the words, our code owns the layout. The
summary is written in the podcast's own language (so Dutch stays Dutch and the
quotes remain the speakers' actual words).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config

# HTTP status codes that mean "try again shortly" rather than "you did something
# wrong": rate limiting (429) and transient server-side load (5xx). Google's
# free tier returns 503 during demand spikes, which is exactly what we retry.
_RETRYABLE_CODES = {429, 500, 502, 503, 504}


@dataclass
class Summary:
    language: str
    theme: str                       # ~50-word teaser (opens the delivery email)
    header: dict[str, Any]           # guests, etc. (show/title/date come from the ledger)
    part1: list[dict[str, str]] = field(default_factory=list)  # {heading, body}
    part2: list[dict[str, Any]] = field(default_factory=list)  # {text, is_quote, explanation}
    part3: list[dict[str, str]] = field(default_factory=list)  # {title, author, description}


# --------------------------------------------------------------------------
# The prompt has two parts:
#   * DEFAULT_INSTRUCTIONS — the human-editable "how to summarize" guidance
#     (section counts, tone, what to include/exclude). Safe to rewrite freely.
#     You can override it without touching code: run `summarize --dump-prompt`
#     to write it to summary_prompt.txt, edit that file, and it's used instead.
#   * _SCHEMA_BLOCK — the fixed JSON shape the PDF renderer depends on. This is
#     NOT editable via the file, so tweaking the instructions can never break
#     parsing or the layout.
# --------------------------------------------------------------------------
DEFAULT_INSTRUCTIONS = """\
You are an expert podcast note-taker. Summarize the transcript into a structured
JSON object matching this three-part format.

PART 1 — Episode summary: 8 to 12 thematic sections. Each has a short, punchy
heading and one rich paragraph. Together the paragraphs total 600-900 words.
Preserve concrete details: named studies, numbers, vivid examples, frameworks.

PART 2 — Key insights, quotes & takeaways: 10 to 15 items. Some are near-verbatim
memorable quotes (set is_quote=true), others are concept labels (is_quote=false).
Each has a 1-3 sentence explanation.

PART 3 — Books & resources mentioned: genuine editorial resources that were
discussed as part of the content — books, papers, studies, tools, companies,
products, or people. Give title, author (empty string if none), and a one-to-two
sentence description. If you are not fully certain something was referenced, say
so in the description (e.g. "likely referenced"). If none, use an empty list.
  EXCLUDE ADVERTISING. Do NOT list the episode's sponsors, ad-reads, paid
  promotions, or product plugs — anything presented in a "this episode is
  brought to you by ..." / sponsored-segment style. Part 3 is only for things
  discussed as editorial substance, never for advertising, even if a sponsor's
  product sounds relevant.

Also write "theme": a ~50-word teaser capturing the episode's throughline, and
"header.guests": the guest/host names you can identify from the transcript
(empty string if unclear). Do NOT invent facts not supported by the transcript.
"""

_SCHEMA_BLOCK = """\
Return ONLY a JSON object (no prose, no markdown fences) with exactly these keys:
{
  "language": "<iso code>",
  "theme": "<~50 words>",
  "header": { "guests": "<names or empty>" },
  "part1": [ { "heading": "<...>", "body": "<...>" } ],
  "part2": [ { "text": "<quote or label>", "is_quote": true, "explanation": "<...>" } ],
  "part3": [ { "title": "<...>", "author": "<...>", "description": "<...>" } ]
}"""


def load_instructions() -> str:
    """Return the editable instructions — from the override file if it exists,
    otherwise the built-in default."""
    path = config.SUMMARY_PROMPT_FILE
    if path and Path(path).exists():
        return Path(path).read_text(encoding="utf-8")
    return DEFAULT_INSTRUCTIONS


def build_prompt(transcript: str, *, show_name: str, episode_title: str,
                 language: str | None) -> str:
    """Assemble the full prompt: language + metadata + instructions + schema."""
    lang_clause = (
        f"Write the ENTIRE summary in this language (ISO code): {language}."
        if language and language != "unknown"
        else "Write the summary in the SAME language the transcript is in."
    )
    return (
        f"{lang_clause}\n\n"
        f"Podcast: {show_name}\nEpisode: {episode_title}\n\n"
        f"{load_instructions()}\n\n"
        f"{_SCHEMA_BLOCK}\n\n"
        f"TRANSCRIPT:\n{transcript}\n"
    )


def _parse_summary_json(raw: str, *, fallback_language: str | None) -> Summary:
    """Parse the model's JSON reply into a Summary, tolerating stray wrapping.

    Models sometimes wrap JSON in ```json fences or add a stray sentence; we
    extract the outermost {...} block before parsing so those don't break us.
    """
    text = raw.strip()
    if "```" in text:
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text.strip())
    # Fall back to slicing the first { to the last } if there's extra prose.
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end + 1]

    data = json.loads(text)
    return Summary(
        language=data.get("language") or fallback_language or "unknown",
        theme=data.get("theme", ""),
        header=data.get("header", {}) or {},
        part1=data.get("part1", []) or [],
        part2=data.get("part2", []) or [],
        part3=data.get("part3", []) or [],
    )


def summarize_transcript(transcript: str, *, show_name: str, episode_title: str,
                         language: str | None = None, backend: str | None = None,
                         model: str | None = None) -> Summary:
    """Summarize a transcript using the configured backend."""
    if not transcript.strip():
        raise ValueError("Transcript is empty — nothing to summarize.")
    backend = backend or config.SUMMARY_BACKEND
    prompt = build_prompt(transcript, show_name=show_name,
                          episode_title=episode_title, language=language)

    if backend == "gemini":
        raw = _call_gemini(prompt, model=model or config.GEMINI_MODEL)
    elif backend in ("claude", "ollama"):
        raise NotImplementedError(
            f"The {backend!r} summary backend isn't wired up yet. "
            "Use SUMMARY_BACKEND=gemini for now."
        )
    else:
        raise ValueError(f"Unknown SUMMARY_BACKEND: {backend!r}")

    return _parse_summary_json(raw, fallback_language=language)


def _call_gemini(prompt: str, *, model: str, max_retries: int = 5) -> str:
    """Send the prompt to Gemini and return the raw text (expected: JSON)."""
    if not config.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Get a free key at "
            "https://aistudio.google.com/apikey and add it to your .env. "
            "See docs/gemini-setup.md."
        )
    try:
        from google import genai
        from google.genai import errors, types
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError(
            "The Gemini SDK isn't installed. Install the optional extra:\n"
            '    pip install -e ".[summarize]"'
        ) from exc

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    gen_config = types.GenerateContentConfig(
        # response_mime_type asks Gemini to emit JSON directly, which pairs with
        # our JSON-shaped prompt for reliable parsing.
        response_mime_type="application/json",
        temperature=0.4,
        # We define no tools, so silence the SDK's automatic-function-calling
        # notice.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            disable=True
        ),
    )

    # Retry transient failures (rate limits, server load) with exponential
    # backoff, so an unattended overnight run rides out a demand spike instead
    # of failing. Non-transient errors (bad key, bad model) fail immediately.
    delay = 5.0
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model, contents=prompt, config=gen_config,
            )
            return response.text or ""
        except errors.APIError as exc:
            code = getattr(exc, "code", None)
            if code not in _RETRYABLE_CODES:
                raise RuntimeError(
                    f"Gemini rejected the request (code {code}): "
                    f"{getattr(exc, 'message', exc)}"
                ) from exc
            last_exc = exc
            if attempt < max_retries:
                print(f"  Gemini busy (code {code}), attempt {attempt}/"
                      f"{max_retries}; retrying in {int(delay)}s…")
                time.sleep(delay)
                delay = min(delay * 2, 60.0)

    raise RuntimeError(
        "Gemini stayed unavailable after several retries — this is a Google-"
        "side load spike, not your setup. The episode is still queued; just "
        "run `summarize` again in a few minutes."
    ) from last_exc
