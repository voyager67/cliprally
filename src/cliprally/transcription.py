"""Optional offline speech transcription with word-level timestamps."""

from __future__ import annotations

from pathlib import Path

from .models import Transcript, Word


class TranscriptionError(RuntimeError):
    """Raised when transcription cannot be completed."""


def transcribe_with_faster_whisper(
    media_path: str | Path,
    *,
    model_size: str = "small",
    device: str = "auto",
    compute_type: str = "int8",
    language: str | None = None,
) -> Transcript:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise TranscriptionError(
            "Offline transcription is optional. Install it with: "
            "pip install 'cliprally[transcription]'"
        ) from exc

    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, info = model.transcribe(
        str(Path(media_path).expanduser().resolve()),
        language=language,
        word_timestamps=True,
        vad_filter=True,
    )
    words: list[Word] = []
    for segment in segments:
        if not segment.words:
            continue
        for item in segment.words:
            text = (item.word or "").strip()
            if not text:
                continue
            start = max(0.0, float(item.start))
            end = max(start, float(item.end))
            words.append(
                Word(
                    text=text,
                    start=start,
                    end=end,
                    probability=float(item.probability)
                    if item.probability is not None
                    else None,
                )
            )
    if not words:
        raise TranscriptionError(
            "No speech words were detected. Check the audio track or try a different model."
        )
    return Transcript(
        words=tuple(words),
        language=getattr(info, "language", language),
        source=f"faster-whisper:{model_size}",
    )