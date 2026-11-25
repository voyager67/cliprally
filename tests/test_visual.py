from __future__ import annotations

import shutil
import subprocess

import pytest

from cliprally.models import ClipCandidate, MediaInfo, Word
from cliprally.pipeline import _rank_hybrid_with_visual, process_video
from cliprally.transcription import TranscriptionError
from cliprally.visual import (
    VisualSample,
    build_visual_candidates,
    sample_visual_activity,
    score_visual_range,
)


def _activity_samples() -> list[VisualSample]:
    samples = []
    for index in range(120):
        timestamp = index * 1.5
        active = 30 <= timestamp <= 72
        samples.append(
            VisualSample(
                timestamp=timestamp,
                motion=8.5 if active else 0.15,
                scene_change=0.68 if active and index % 5 == 0 else 0.02,
            )
        )
    return samples


def test_visual_candidates_prioritize_active_windows_and_spread_results() -> None:
    samples = _activity_samples()
    candidates = build_visual_candidates(
        samples, duration=180, min_duration=15, max_duration=55, max_candidates=10
    )
    assert candidates
    assert candidates[0].score > 50
    assert 15 <= candidates[0].start <= 50
    assert all(candidate.duration == pytest.approx(30.0) for candidate in candidates)
    for index, candidate in enumerate(candidates):
        assert all(
            max(0.0, min(candidate.end, other.end) - max(candidate.start, other.start))
            / min(candidate.duration, other.duration)
            <= 0.45
            for other in candidates[index + 1 :]
        )


def test_score_visual_range_distinguishes_static_and_active_sections() -> None:
    samples = _activity_samples()
    static_score, static_reason = score_visual_range(samples, start=90, end=120)
    action_score, action_reason = score_visual_range(samples, start=30, end=60)
    assert action_score > static_score
    assert "visual activity" in action_reason
    assert "scene changes" in static_reason


def test_visual_sample_validation() -> None:
    with pytest.raises(ValueError, match="finite"):
        VisualSample(float("nan"), 0, 0)
    with pytest.raises(ValueError, match="valid ranges"):
        VisualSample(0, -1, 0)


def test_hybrid_ranking_can_surface_visual_only_silent_moments() -> None:
    transcript = [
        ClipCandidate(
            0,
            30,
            0,
            "pending",
            tuple(Word("ordinary", index * 0.5, index * 0.5 + 0.2) for index in range(50)),
        )
    ]
    visual = [ClipCandidate(60, 90, 88, "visual action", ())]
    ranked = _rank_hybrid_with_visual(
        transcript,
        visual,
        visual_samples=_activity_samples(),
        scorer="heuristic",
        scorer_model=None,
        words=transcript[0].words,
    )
    assert ranked[0].start == 60
    assert ranked[0].reason == "visual action"


def test_visual_mode_skips_transcription_and_renders_empty_word_moments(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "silent.mp4"
    source.write_bytes(b"synthetic")
    info = MediaInfo(str(source), 120.0, 1280, 720, "h264", None, 30.0)
    samples = _activity_samples()
    monkeypatch.setattr("cliprally.pipeline.probe_media", lambda _path: info)
    monkeypatch.setattr("cliprally.pipeline.sample_visual_activity", lambda *a, **k: samples)

    def forbidden_transcription(*_args, **_kwargs):
        raise AssertionError("visual mode must not run speech transcription")

    monkeypatch.setattr(
        "cliprally.pipeline.transcribe_with_faster_whisper", forbidden_transcription
    )

    def fake_render(_source, candidate, destination, **_kwargs):
        assert not candidate.words
        return destination

    monkeypatch.setattr("cliprally.pipeline.render_clip", fake_render)
    result = process_video(
        source,
        tmp_path / "out",
        clips=2,
        moment_mode="visual",
        min_duration=15,
        max_duration=55,
    )
    assert result["moment_mode"] == "visual"
    assert result["transcript"]["source"] == "visual-only"
    assert result["visual_analysis"]["samples_analysed"] == len(samples)
    assert len(result["clips"]) == 2
    assert all("visual activity" in item["reason"] for item in result["clips"])


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="FFmpeg is not installed",
)
def test_opencv_can_analyse_generated_motion_video(tmp_path) -> None:
    pytest.importorskip("cv2")
    source = tmp_path / "motion.mp4"
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
            "testsrc2=size=320x180:rate=12:duration=6",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    samples = sample_visual_activity(source, duration=6, sample_interval=0.5)
    assert len(samples) >= 8
    assert any(sample.motion > 0 for sample in samples)


def test_hybrid_mode_falls_back_to_visual_when_transcription_is_silent(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "silent.mp4"
    source.write_bytes(b"synthetic")
    info = MediaInfo(str(source), 120.0, 1280, 720, "h264", None, 30.0)
    samples = _activity_samples()
    monkeypatch.setattr("cliprally.pipeline.probe_media", lambda _path: info)
    monkeypatch.setattr("cliprally.pipeline.sample_visual_activity", lambda *a, **k: samples)

    def no_speech(*_args, **_kwargs):
        raise TranscriptionError("No speech words were detected. Check the audio track.")

    monkeypatch.setattr("cliprally.pipeline.transcribe_with_faster_whisper", no_speech)
    monkeypatch.setattr(
        "cliprally.pipeline.render_clip",
        lambda _source, _candidate, destination, **_kwargs: destination,
    )
    result = process_video(
        source,
        tmp_path / "out",
        clips=1,
        moment_mode="hybrid",
        min_duration=15,
        max_duration=55,
    )
    assert result["transcript"]["source"] == "no-speech"
    assert result["clips"][0]["reason"].startswith("visual activity")