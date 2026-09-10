"""Turn an episode's audio file into a text transcript (Stage 3).

Design: a small pluggable "backend" seam
-----------------------------------------
Transcription can be done by different engines. Right now we use
**faster-whisper** because it's painless on a PC (one pip install, downloads the
model itself, decodes MP3s without a separate ffmpeg). Later, on the Raspberry
Pi, we'll use **whisper.cpp**. Both do the same job — audio in, text out — so we
hide them behind one function, `transcribe_file()`, that returns the same
`TranscriptResult` no matter which engine ran. Nothing else in the pipeline has
to know or care which was used.

Everyday analogy: it's like a "print" button that works the same whether the
office has an inkjet or a laser printer behind the wall. You press print; the
right machine handles it.

Whisper models are heavy dependencies, so they are NOT installed by default.
The faster-whisper library is an optional extra:

    pip install -e ".[whisper]"

Calling a backend that isn't installed raises a clear, actionable error rather
than a cryptic ImportError.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import config


@dataclass
class Segment:
    """One timestamped chunk of speech (seconds from the start)."""
    start: float
    end: float
    text: str


@dataclass
class TranscriptResult:
    """Everything Stage 4 might want from a transcription."""
    text: str
    language: str
    duration: float
    segments: list[Segment] = field(default_factory=list)


# A progress callback receives (seconds_transcribed, total_seconds) so the CLI
# can show a live "37%/1h07m" style readout during a long job.
ProgressFn = Callable[[float, float], None]


def transcribe_file(
    audio_path: Path,
    *,
    backend: str | None = None,
    model: str | None = None,
    language: str | None = None,
    progress: ProgressFn | None = None,
) -> TranscriptResult:
    """Transcribe one audio file using the configured backend."""
    backend = backend or config.WHISPER_BACKEND
    if backend == "faster-whisper":
        return _transcribe_faster_whisper(
            audio_path, model=model or config.WHISPER_MODEL,
            language=language if language is not None else config.WHISPER_LANGUAGE,
            progress=progress,
        )
    if backend == "whisper.cpp":
        # Reserved for the Raspberry Pi deployment; implemented in a later stage.
        raise NotImplementedError(
            "The whisper.cpp backend isn't wired up yet — we'll add it when we "
            "set up the Pi. For now use WHISPER_BACKEND=faster-whisper."
        )
    raise ValueError(f"Unknown WHISPER_BACKEND: {backend!r}")


def _transcribe_faster_whisper(
    audio_path: Path,
    *,
    model: str,
    language: str | None,
    progress: ProgressFn | None,
) -> TranscriptResult:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError(
            "faster-whisper isn't installed. Install the optional extra:\n"
            '    pip install -e ".[whisper]"'
        ) from exc

    # Loading the model downloads it (~500 MB for "small") on first use, then
    # caches it. device/compute_type come from config so the Pi can differ.
    wmodel = WhisperModel(
        model, device=config.WHISPER_DEVICE,
        compute_type=config.WHISPER_COMPUTE_TYPE,
    )

    # vad_filter skips long silences, which speeds things up and avoids the
    # model "hallucinating" text during quiet gaps.
    segments_iter, info = wmodel.transcribe(
        str(audio_path), language=language, vad_filter=True,
    )

    total = float(getattr(info, "duration", 0.0) or 0.0)
    collected: list[Segment] = []
    parts: list[str] = []
    # faster-whisper yields segments lazily AS it transcribes, so iterating is
    # what actually does the work — and lets us report progress in real time.
    for seg in segments_iter:
        collected.append(Segment(start=seg.start, end=seg.end, text=seg.text))
        parts.append(seg.text)
        if progress:
            progress(float(seg.end), total)

    text = "".join(parts).strip()
    return TranscriptResult(
        text=text,
        language=getattr(info, "language", language or "unknown"),
        duration=total,
        segments=collected,
    )
