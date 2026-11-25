"""End-to-end local video-to-clips workflow."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .media import probe_media
from .metadata import suggest_metadata
from .models import ClipCandidate, Transcript, Word
from .moments import build_candidates, heuristic_score, rank_candidates
from .render import render_clip
from .transcription import TranscriptionError, transcribe_with_faster_whisper
from .visual import build_visual_candidates, sample_visual_activity, score_visual_range


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
    fallback = "visual-moment" if not phrase else "moment"
    return f"{index:02d}-{slug or fallback}"


def _overlap_ratio(first: ClipCandidate, second: ClipCandidate) -> float:
    intersection = max(0.0, min(first.end, second.end) - max(first.start, second.start))
    shorter = min(first.duration, second.duration)
    return intersection / shorter if shorter > 0 else 0.0


def _words_in_range(
    words: tuple[Word, ...], start: float, end: float
) -> tuple[Word, ...]:
    return tuple(word for word in words if word.end > start and word.start < end)


def _rank_hybrid_with_visual(
    transcript_candidates: list[ClipCandidate],
    visual_candidates: list[ClipCandidate],
    *,
    visual_samples: list[Any],
    scorer: str,
    scorer_model: str | None,
    words: tuple[Word, ...],
) -> list[ClipCandidate]:
    """Blend transcript and visual evidence, retaining visual-only moments."""
    ranked_text = (
        rank_candidates(transcript_candidates, scorer=scorer, model=scorer_model)
        if transcript_candidates
        else []
    )
    ranked: list[ClipCandidate] = []

    # Keep transcript candidate boundaries, but reward segments with visible action.
    # Text contributes more than motion so static talking-head content still works.
    for candidate in ranked_text:
        visual_score, visual_reason = score_visual_range(
            visual_samples, start=candidate.start, end=candidate.end
        )
        score = round(0.75 * candidate.score + 0.25 * visual_score, 1)
        ranked.append(
            ClipCandidate(
                candidate.start,
                candidate.end,
                score,
                f"{candidate.reason}; {visual_reason} ({visual_score:.0f}/100)",
                candidate.words,
            )
        )

    for candidate in visual_candidates:
        if any(_overlap_ratio(candidate, text_item) > 0.45 for text_item in ranked_text):
            continue
        attached_words = _words_in_range(words, candidate.start, candidate.end)
        score = candidate.score
        reason = candidate.reason
        if attached_words:
            text_candidate = heuristic_score(
                ClipCandidate(
                    candidate.start, candidate.end, 0.0, "transcript support", attached_words
                )
            )
            score = round(0.70 * candidate.score + 0.30 * text_candidate.score, 1)
            reason = f"{reason}; transcript support"
        ranked.append(
            ClipCandidate(candidate.start, candidate.end, score, reason, attached_words)
        )

    ranked.sort(key=lambda item: item.score, reverse=True)

    # Greedy temporal diversity prevents a long action burst from filling every slot.
    selected: list[ClipCandidate] = []
    for candidate in ranked:
        if any(_overlap_ratio(candidate, previous) > 0.55 for previous in selected):
            continue
        selected.append(candidate)
    return selected


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
    moment_mode: str = "transcript",
    visual_sample_interval: float = 1.5,
) -> dict[str, Any]:
    if clips < 1:
        raise ValueError("clips must be at least 1")
    if min_duration <= 0 or max_duration < min_duration:
        raise ValueError("Expected 0 < min_duration <= max_duration")
    if moment_mode not in {"transcript", "hybrid", "visual"}:
        raise ValueError("moment_mode must be transcript, hybrid, or visual")

    input_path = Path(source).expanduser().resolve()
    info = probe_media(input_path)
    transcript = Transcript(words=(), language=language, source="visual-only")
    bounded_words: list[Word] = []

    if moment_mode != "visual":
        try:
            raw_transcript = (
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
        except TranscriptionError as exc:
            # Silence is a valid input for visual/hybrid mode. Missing models and
            # other transcription failures still surface their actionable errors.
            if moment_mode != "hybrid" or "No speech words were detected" not in str(exc):
                raise
            raw_transcript = Transcript(words=(), language=language, source="no-speech")

        for word in raw_transcript.words:
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
        transcript = Transcript(
            words=tuple(bounded_words),
            language=raw_transcript.language,
            source=raw_transcript.source if bounded_words else "no-speech",
        )
        if not bounded_words and moment_mode == "transcript":
            raise RuntimeError(
                "No valid transcript words fall within the source video's duration"
            )

    transcript_candidates = (
        build_candidates(
            transcript.words,
            min_duration=min_duration,
            max_duration=max_duration,
        )
        if transcript.words
        else []
    )

    visual_samples = []
    visual_candidates: list[ClipCandidate] = []
    if moment_mode in {"hybrid", "visual"}:
        visual_samples = sample_visual_activity(
            input_path,
            duration=info.duration,
            sample_interval=visual_sample_interval,
        )
        visual_candidates = build_visual_candidates(
            visual_samples,
            duration=info.duration,
            min_duration=min_duration,
            max_duration=max_duration,
            max_candidates=max(12, clips * 8),
        )

    if moment_mode == "transcript":
        if not transcript_candidates:
            raise RuntimeError(
                "No clip-sized speech segments were found. Try a shorter --min-duration, "
                "a longer source, or provide a better transcript."
            )
        ranked = rank_candidates(
            transcript_candidates, scorer=scorer, model=scorer_model
        )
    elif moment_mode == "visual":
        ranked = [
            ClipCandidate(
                candidate.start,
                candidate.end,
                candidate.score,
                candidate.reason,
                _words_in_range(transcript.words, candidate.start, candidate.end),
            )
            for candidate in visual_candidates
        ]
    else:
        ranked = _rank_hybrid_with_visual(
            transcript_candidates,
            visual_candidates,
            visual_samples=visual_samples,
            scorer=scorer,
            scorer_model=scorer_model,
            words=transcript.words,
        )

    if not ranked:
        raise RuntimeError(
            "No usable moments were found. Try a different source or shorter clip duration."
        )
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
        "scorer": "visual-motion" if moment_mode == "visual" else scorer,
        "moment_mode": moment_mode,
        "visual_analysis": {
            "enabled": moment_mode in {"hybrid", "visual"},
            "method": "OpenCV optical flow and grayscale histogram changes",
            "sample_interval_seconds": visual_sample_interval,
            "samples_analysed": len(visual_samples),
            "candidate_windows": len(visual_candidates),
        },
        "clips": rendered,
        "metadata_path": str(metadata_path),
    }
    manifest_path = destination / "manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest