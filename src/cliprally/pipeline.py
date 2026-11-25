"""End-to-end local video-to-clips workflow."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .media import probe_media
from .metadata import suggest_metadata
from .models import ClipCandidate, Transcript, Word
from .moments import build_candidates, rank_candidates
from .render import render_clip
from .transcription import transcribe_with_faster_whisper


def load_transcript_json(path: str | Path) -> Transcript:
    payload: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    words = tuple(
        Word(
            text=str(item["text"]),
            start=float(item["start"]),
            end=float(item["end"]),
            probability=float(item["probability"]) if item.get("probability") is not None else None,
        )
        for item in payload.get("words", [])
    )
    if not words:
        raise ValueError("Transcript JSON must contain a non-empty 'words' array")
    return Transcript(words=words, language=payload.get("language"), source="json")


def _filename_title(candidate: ClipCandidate, index: int) -> str:
    phrase = " ".join(word.text for word in candidate.words[:8])
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", phrase.lower()).strip("-")[:48]
    return f"{index:02d}-{slug or 'moment'}"


def process_video(
    source: str | Path,
    output_dir: str | Path,
    *,
    clips: int = 3,
    model_size: str = "small",
    device: str = "auto",
    compute_type: str = "int8",
    language: str | None = None,
    scorer: str = "heuristic",
    scorer_model: str | None = None,
    min_duration: float = 15.0,
    max_duration: float = 55.0,
    captions: bool = True,
    face_tracking: bool = False,
    encoder: str = "libx264",
    transcript_json: str | Path | None = None,
) -> dict[str, Any]:
    if clips < 1:
        raise ValueError("clips must be at least 1")
    if min_duration <= 0 or max_duration < min_duration:
        raise ValueError("Expected 0 < min_duration <= max_duration")
    input_path = Path(source).expanduser().resolve()
    info = probe_media(input_path)
    transcript = (
        load_transcript_json(transcript_json)
        if transcript_json
        else transcribe_with_faster_whisper(
            input_path,
            model_size=model_size,
            device=device,
            compute_type=compute_type,
            language=language,
        )
    )
    # Reject or clamp malformed external transcript timings so no generated clip
    # or subtitle event can describe media outside the probed source duration.
    bounded_words: list[Word] = []
    for word in transcript.words:
        if word.start >= info.duration:
            continue
        bounded_start = max(0.0, word.start)
        bounded_end = min(info.duration, word.end)
        if bounded_end > bounded_start:
            bounded_words.append(
                Word(
                    text=word.text,
                    start=bounded_start,
                    end=bounded_end,
                    probability=word.probability,
                )
            )
    if not bounded_words:
        raise RuntimeError("No valid transcript words fall within the source video's duration")
    transcript = Transcript(
        words=tuple(bounded_words), language=transcript.language, source=transcript.source
    )
    candidates = build_candidates(
        transcript.words,
        min_duration=min_duration,
        max_duration=max_duration,
    )
    if not candidates:
        raise RuntimeError(
            "No clip-sized speech segments were found. Try a shorter --min-duration, "
            "a longer source, or provide a better transcript."
        )
    ranked = rank_candidates(candidates, scorer=scorer, model=scorer_model)
    selected = ranked[: max(1, clips)]

    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    rendered: list[dict[str, Any]] = []
    for index, candidate in enumerate(selected, start=1):
        target = destination / f"{_filename_title(candidate, index)}.mp4"
        output = render_clip(
            input_path,
            candidate,
            target,
            caption_words=transcript.words,
            captions=captions,
            face_tracking=face_tracking,
            encoder=encoder,
        )
        rendered.append(
            {
                "path": str(output),
                **candidate.to_dict(),
                "suggested_metadata": suggest_metadata(candidate.words),
            }
        )

    metadata_items = [
        {
            "file": Path(item["path"]).name,
            "title": item["suggested_metadata"]["title"],
            "hashtags": item["suggested_metadata"]["hashtags"],
            "score": item["score"],
            "reason": item["reason"],
        }
        for item in rendered
    ]
    metadata_path = destination / "metadata.json"
    metadata_path.write_text(
        json.dumps({"clips": metadata_items}, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    manifest = {
        "project": "ClipRally",
        "version": "1.0.0",
        "source": str(input_path),
        "media": {
            "duration": info.duration,
            "width": info.width,
            "height": info.height,
            "video_codec": info.video_codec,
            "audio_codec": info.audio_codec,
        },
        "transcript": {"language": transcript.language, "source": transcript.source},
        "scorer": scorer,
        "clips": rendered,
        "metadata_path": str(metadata_path),
    }
    manifest_path = destination / "manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest