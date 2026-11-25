"""FFmpeg-based vertical clip rendering."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .captions import write_karaoke_ass
from .media import MediaError, probe_media, require_binary
from .models import ClipCandidate, Word
from .reframe import crop_x_expression, detect_face_centers


def _escape_filter_path(path: Path) -> str:
    # FFmpeg filter options have their own quoting rules (separate from the
    # subprocess argument list). Close/reopen single quotes around apostrophes.
    value = str(path.resolve()).replace("\\", "\\\\").replace(":", "\\:")
    return value.replace("'", "'\\''")


def _video_filter(
    width: int,
    height: int,
    *,
    face_points: list[tuple[float, float]] | None = None,
    subtitle_path: Path | None = None,
) -> str:
    # Portrait and near-square footage is fitted into a 9:16 canvas with a crop.
    if width / max(1, height) > 9 / 16:
        crop_width = height * 9 / 16
        x_expression = crop_x_expression(width, crop_width, face_points or [])
        filters = [f"crop=w={crop_width:.3f}:h=ih:x='{x_expression}':y=0"]
    else:
        crop_height = width * 16 / 9
        y_expression = f"max(0,min(ih-oh,(ih-oh)/2))"
        filters = [f"crop=w=iw:h={crop_height:.3f}:x=0:y='{y_expression}'"]
    filters.extend(["scale=1080:1920:flags=lanczos", "setsar=1"])
    if subtitle_path is not None:
        filters.append(f"subtitles=filename='{_escape_filter_path(subtitle_path)}'")
    return ",".join(filters)


def render_clip(
    source: str | Path,
    candidate: ClipCandidate,
    destination: str | Path,
    *,
    caption_words: tuple[Word, ...] | list[Word] = (),
    captions: bool = True,
    face_tracking: bool = False,
    encoder: str = "libx264",
    preset: str = "veryfast",
    crf: int = 21,
) -> Path:
    if encoder not in {"libx264", "h264_nvenc", "h264_videotoolbox"}:
        raise ValueError("encoder must be libx264, h264_nvenc, or h264_videotoolbox")
    if not 0 <= crf <= 51:
        raise ValueError("crf must be between 0 and 51")
    if not preset.strip():
        raise ValueError("preset must not be empty")
    source_path = Path(source).expanduser().resolve()
    info = probe_media(source_path)
    start = max(0.0, min(candidate.start, info.duration))
    end = max(start, min(candidate.end, info.duration))
    if end - start < 0.35:
        raise MediaError("Clip is too short to render (minimum 0.35 seconds)")

    target = Path(destination).expanduser().resolve()
    if target == source_path:
        raise ValueError("Output path must not overwrite the source video")
    target.parent.mkdir(parents=True, exist_ok=True)
    subtitle_words = [
        Word(
            text=word.text,
            start=max(0.0, word.start - start),
            end=max(0.0, word.end - start),
            probability=word.probability,
        )
        for word in caption_words
        if word.end >= start and word.start <= end
    ] if captions else []

    # Keep the temporary subtitle path simple and independent of user-controlled
    # output paths (which may contain commas, quotes, or other filtergraph syntax).
    with tempfile.TemporaryDirectory(prefix="cliprally-subtitles-") as temp_dir:
        subtitle_file: Path | None = None
        if subtitle_words:
            subtitle_file = Path(temp_dir) / "captions.ass"
            write_karaoke_ass(subtitle_words, subtitle_file)

        face_points: list[tuple[float, float]] = []
        if face_tracking and info.width / max(1, info.height) > 9 / 16:
            face_points = detect_face_centers(source, start=start, duration=end - start)

        filters = _video_filter(
            info.width,
            info.height,
            face_points=face_points,
            subtitle_path=subtitle_file,
        )
        ffmpeg = require_binary("ffmpeg")
        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(source_path),
            "-t",
            f"{end - start:.3f}",
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-vf",
            filters,
            "-c:v",
            encoder,
        ]
        if info.audio_codec:
            command += ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"]
        if encoder == "libx264":
            command += ["-preset", preset, "-crf", str(crf)]
        elif encoder == "h264_nvenc":
            command += ["-preset", "p4", "-cq", str(crf)]
        elif encoder == "h264_videotoolbox":
            command += ["-b:v", "8M"]
        command += [
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(target),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            raise MediaError("FFmpeg executable was not found") from exc
        if result.returncode != 0:
            target.unlink(missing_ok=True)
            raise MediaError(result.stderr.strip()[-4000:] or "FFmpeg render failed")
    return target