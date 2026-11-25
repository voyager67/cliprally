"""Lightweight local visual-activity analysis for highlight candidate discovery.

This module measures optical-flow motion and shot changes. It does not understand
objects, game events, faces, story context, or whether an action is entertaining.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ClipCandidate


@dataclass(frozen=True, slots=True)
class VisualSample:
    """Motion and scene-change measurements at one sampled video timestamp."""

    timestamp: float
    motion: float
    scene_change: float

    def __post_init__(self) -> None:
        values = (self.timestamp, self.motion, self.scene_change)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Visual sample values must be finite")
        if self.timestamp < 0 or self.motion < 0 or not 0 <= self.scene_change <= 1:
            raise ValueError("Visual sample values are outside their valid ranges")


def sample_visual_activity(
    media_path: str | Path,
    *,
    duration: float,
    sample_interval: float = 1.5,
    max_width: int = 320,
) -> list[VisualSample]:
    """Sample a video and measure motion plus histogram-based shot changes.

    Frames are reduced before analysis to keep the CPU workload manageable. OpenCV
    is imported lazily because visual analysis is an optional installation extra.
    """
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("duration must be positive and finite")
    if not math.isfinite(sample_interval) or sample_interval < 0.25:
        raise ValueError("sample_interval must be at least 0.25 seconds")
    if max_width < 96:
        raise ValueError("max_width must be at least 96 pixels")

    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "Visual highlight analysis requires OpenCV. Install it with: "
            "pip install 'cliprally[visual-analysis]'"
        ) from exc

    path = Path(media_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Video file does not exist: {path}")

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise RuntimeError("OpenCV could not open the source video for visual analysis")

    samples: list[VisualSample] = []
    previous_gray: Any = None
    previous_histogram: Any = None
    try:
        timestamp = 0.0
        while timestamp < duration:
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
            ok, frame = capture.read()
            if not ok:
                break

            height, width = frame.shape[:2]
            scale = min(1.0, max_width / max(1, width))
            if scale < 1.0:
                frame = cv2.resize(
                    frame,
                    (max(1, int(width * scale)), max(1, int(height * scale))),
                    interpolation=cv2.INTER_AREA,
                )
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            histogram = cv2.calcHist([gray], [0], None, [32], [0, 256])
            cv2.normalize(histogram, histogram, alpha=1.0, norm_type=cv2.NORM_L1)

            motion = 0.0
            scene_change = 0.0
            if previous_gray is not None and previous_histogram is not None:
                flow = cv2.calcOpticalFlowFarneback(
                    previous_gray,
                    gray,
                    None,
                    0.5,
                    2,
                    9,
                    2,
                    5,
                    1.1,
                    0,
                )
                magnitude = cv2.magnitude(flow[..., 0], flow[..., 1])
                motion = float(magnitude.mean())
                scene_change = float(
                    cv2.compareHist(
                        previous_histogram, histogram, cv2.HISTCMP_BHATTACHARYYA
                    )
                )
                scene_change = max(0.0, min(1.0, scene_change))

            samples.append(
                VisualSample(
                    timestamp=min(timestamp, duration),
                    motion=max(0.0, motion),
                    scene_change=scene_change,
                )
            )
            previous_gray = gray
            previous_histogram = histogram
            timestamp += sample_interval
    finally:
        capture.release()

    if len(samples) < 2:
        raise RuntimeError(
            "Visual analysis could not sample enough frames. Try a longer or supported video."
        )
    return samples


def _window_score(
    samples: list[VisualSample], *, scene_cut_threshold: float = 0.42
) -> tuple[float, float, int]:
    if not samples:
        return 0.0, 0.0, 0
    motion_values = [sample.motion for sample in samples]
    mean_motion = sum(motion_values) / len(motion_values)
    peak_motion = max(motion_values)
    scene_cuts = sum(sample.scene_change >= scene_cut_threshold for sample in samples)

    # These are interpretable signal heuristics, not learned event probabilities.
    mean_component = min(mean_motion / 5.5, 1.0)
    peak_component = min(peak_motion / 14.0, 1.0)
    cut_component = min(scene_cuts / max(1.0, len(samples) / 12.0), 1.0)
    score = 100.0 * (
        0.65 * mean_component + 0.20 * peak_component + 0.15 * cut_component
    )
    return round(max(0.0, min(100.0, score)), 1), round(mean_motion, 2), scene_cuts


def score_visual_range(
    samples: list[VisualSample], *, start: float, end: float
) -> tuple[float, str]:
    """Return a visual-activity score for a time range and an explainable reason."""
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise ValueError("Expected a valid visual analysis time range")
    window = [sample for sample in samples if start < sample.timestamp <= end]
    score, mean_motion, scene_cuts = _window_score(window)
    reason = f"visual activity (motion {mean_motion:.1f}, {scene_cuts} scene changes)"
    return score, reason


def build_visual_candidates(
    samples: list[VisualSample],
    *,
    duration: float,
    min_duration: float = 15.0,
    max_duration: float = 55.0,
    max_candidates: int = 32,
) -> list[ClipCandidate]:
    """Create diverse, fixed-length candidates from the strongest activity windows."""
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("duration must be positive and finite")
    if min_duration <= 0 or max_duration < min_duration:
        raise ValueError("Expected 0 < min_duration <= max_duration")
    if max_candidates < 1:
        raise ValueError("max_candidates must be at least 1")

    clip_duration = min(duration, min(max_duration, max(min_duration, 30.0)))
    if clip_duration < 0.35:
        raise ValueError("Source video is too short to create a visual clip")
    stride = max(3.0, min(clip_duration / 5.0, 10.0))
    last_start = max(0.0, duration - clip_duration)
    starts: list[float] = []
    current = 0.0
    while current <= last_start:
        starts.append(current)
        current += stride
    if not starts or last_start - starts[-1] > stride * 0.35:
        starts.append(last_start)

    proposals: list[ClipCandidate] = []
    for start in starts:
        end = min(duration, start + clip_duration)
        window = [sample for sample in samples if start < sample.timestamp <= end]
        if not window:
            continue
        score, mean_motion, scene_cuts = _window_score(window)
        if score < 2.0:
            continue
        reason = f"visual activity (motion {mean_motion:.1f}, {scene_cuts} scene changes)"
        proposals.append(ClipCandidate(start, end, score, reason, ()))

    # Non-maximum suppression keeps the shortlist spread across the recording
    # instead of returning many almost-identical windows around one action burst.
    selected: list[ClipCandidate] = []
    for candidate in sorted(proposals, key=lambda item: item.score, reverse=True):
        overlaps = False
        for previous in selected:
            intersection = max(
                0.0, min(candidate.end, previous.end) - max(candidate.start, previous.start)
            )
            shorter = min(candidate.duration, previous.duration)
            if shorter > 0 and intersection / shorter > 0.45:
                overlaps = True
                break
        if not overlaps:
            selected.append(candidate)
        if len(selected) >= max_candidates:
            break
    return sorted(selected, key=lambda item: item.score, reverse=True)