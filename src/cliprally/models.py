"""Shared, dependency-light data models."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    start: float
    end: float
    probability: float | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("Word text must not be empty")
        if not math.isfinite(self.start) or not math.isfinite(self.end):
            raise ValueError("Word timestamps must be finite numbers")
        if self.start < 0 or self.end < self.start:
            raise ValueError("Word timestamps must be non-negative and ordered")
        if self.probability is not None and (
            not math.isfinite(self.probability) or not 0.0 <= self.probability <= 1.0
        ):
            raise ValueError("Word probability must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ClipCandidate:
    start: float
    end: float
    score: float
    reason: str
    words: tuple[Word, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (self.start, self.end, self.score)):
            raise ValueError("Candidate timestamps and score must be finite numbers")
        if self.start < 0 or self.end <= self.start:
            raise ValueError("Clip candidate must have a positive, non-negative time range")
        if not 0 <= self.score <= 100:
            raise ValueError("Score must be between 0 and 100")
        if not isinstance(self.reason, str):
            raise ValueError("Candidate reason must be text")

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["duration"] = round(self.duration, 3)
        return data


@dataclass(frozen=True, slots=True)
class MediaInfo:
    path: str
    duration: float
    width: int
    height: int
    video_codec: str | None = None
    audio_codec: str | None = None
    fps: float | None = None


@dataclass(frozen=True, slots=True)
class Transcript:
    words: tuple[Word, ...]
    language: str | None = None
    source: str = "unknown"