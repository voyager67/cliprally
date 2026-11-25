"""Media probing and binary discovery using FFmpeg's command-line tools."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .models import MediaInfo


class MediaError(RuntimeError):
    """Raised when media cannot be inspected or processed."""


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise MediaError(
            f"Required executable '{name}' was not found. Install FFmpeg and ensure it is on PATH."
        )
    return path


def probe_media(path: str | Path) -> MediaInfo:
    media_path = Path(path).expanduser().resolve()
    if not media_path.is_file():
        raise FileNotFoundError(f"Video file does not exist: {media_path}")

    ffprobe = require_binary("ffprobe")
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate",
        "-of",
        "json",
        str(media_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise MediaError(result.stderr.strip() or "ffprobe could not read the media file")

    try:
        payload: dict[str, Any] = json.loads(result.stdout)
        streams = payload.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        if video is None:
            raise MediaError("The input does not contain a video stream")
        duration = float(payload.get("format", {}).get("duration", 0.0))
        if not math.isfinite(duration) or duration <= 0:
            raise MediaError("The input has no readable duration")
        width, height = int(video.get("width", 0)), int(video.get("height", 0))
        if width <= 0 or height <= 0:
            raise MediaError("The input has invalid video dimensions")
        fps = _parse_fraction(video.get("avg_frame_rate"))
        return MediaInfo(
            path=str(media_path),
            duration=duration,
            width=width,
            height=height,
            video_codec=video.get("codec_name"),
            audio_codec=audio.get("codec_name") if audio else None,
            fps=fps,
        )
    except (TypeError, ValueError, KeyError, StopIteration) as exc:
        raise MediaError("Could not parse ffprobe output") from exc


def _parse_fraction(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    try:
        numerator, denominator = value.split("/", 1)
        return float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        return None