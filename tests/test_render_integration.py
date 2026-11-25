from __future__ import annotations

import shutil
import subprocess

import pytest

from cliprally.media import probe_media
from cliprally.models import ClipCandidate, Word
from cliprally.render import render_clip


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="FFmpeg is not installed",
)
def test_ffmpeg_renders_a_vertical_captioned_clip(tmp_path) -> None:
    work_dir = tmp_path / "nested, 'quotes' folder"
    work_dir.mkdir()
    source = work_dir / "source.mp4"
    command = [
        shutil.which("ffmpeg") or "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=size=640x360:rate=25",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000",
        "-t",
        "3",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(source),
    ]
    subprocess.run(command, check=True, capture_output=True)
    words = [
        Word("This", 0.2, 0.45),
        Word("is", 0.48, 0.62),
        Word("a", 0.64, 0.72),
        Word("render", 0.74, 1.1),
        Word("test", 1.12, 1.42),
        Word("for", 1.5, 1.68),
        Word("ClipRally.", 1.72, 2.25),
    ]
    candidate = ClipCandidate(0.1, 2.8, 90, "integration fixture", tuple(words))
    target = render_clip(
        source,
        candidate,
        work_dir / "vertical, 'clip'.mp4",
        caption_words=words,
        captions=True,
        face_tracking=False,
    )
    assert target.is_file()
    info = probe_media(target)
    assert (info.width, info.height) == (1080, 1920)
    assert info.audio_codec == "aac"
    assert 2.4 <= info.duration <= 2.9


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="FFmpeg is not installed",
)
def test_full_pipeline_from_transcript_json(tmp_path) -> None:
    import json

    from cliprally.pipeline import process_video

    source = tmp_path / "input.mp4"
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=640x360:rate=25",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=330:sample_rate=48000",
            "-t",
            "4",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    transcript = tmp_path / "transcript.json"
    words = [
        {"text": word, "start": start, "end": start + 0.22}
        for word, start in zip(
            ["This", "is", "a", "complete", "local", "ClipRally", "pipeline", "test.", "outside"],
            [0.2, 0.5, 0.8, 1.1, 1.5, 1.9, 2.5, 3.0, 4.8],
            strict=False,
        )
    ]
    transcript.write_text(json.dumps({"language": "en", "words": words}), encoding="utf-8")
    result = process_video(
        source,
        tmp_path / "clips",
        clips=2,
        scorer="heuristic",
        min_duration=1.0,
        max_duration=2.2,
        transcript_json=transcript,
    )
    assert result["clips"]
    assert (tmp_path / "clips" / "manifest.json").is_file()
    assert (tmp_path / "clips" / "metadata.json").is_file()
    assert result["manifest_path"] == str(tmp_path / "clips" / "manifest.json")
    assert result["metadata_path"] == str(tmp_path / "clips" / "metadata.json")
    for item in result["clips"]:
        assert "suggested_metadata" in item
        assert item["end"] <= 4.0
        clip_info = probe_media(item["path"])
        assert clip_info.width == 1080
        assert clip_info.height == 1920


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="FFmpeg is not installed",
)
def test_silent_video_can_be_rendered(tmp_path) -> None:
    source = tmp_path / "silent.mp4"
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=640x360:r=25",
            "-t",
            "1.2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    candidate = ClipCandidate(0.0, 1.1, 70, "silent video", ())
    output = render_clip(source, candidate, tmp_path / "silent-vertical.mp4", captions=False)
    assert probe_media(output).audio_codec is None