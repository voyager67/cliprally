"""Candidate segmentation and optional LLM-assisted moment ranking."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from .models import ClipCandidate, Word

_HOOK_TERMS = {
    "actually", "impossible", "secret", "mistake", "never", "always", "why", "how",
    "truth", "realized", "crazy", "insane", "incredible", "because", "finally",
    "wrong", "right", "first", "best", "worst", "surprise", "shocking", "instead",
}
_EMOTION_TERMS = {
    "love", "hate", "fear", "angry", "happy", "sad", "excited", "win", "fail",
    "destroyed", "amazing", "terrible", "beautiful", "hilarious", "wow", "damn",
}


class MomentScorer(Protocol):
    def score(self, candidates: list[ClipCandidate]) -> list[ClipCandidate]: ...


def build_candidates(
    words: tuple[Word, ...] | list[Word],
    *,
    min_duration: float = 18.0,
    max_duration: float = 55.0,
    max_gap: float = 1.2,
) -> list[ClipCandidate]:
    """Build clip-sized chunks near sentence boundaries and long pauses."""
    if not words:
        return []
    if min_duration <= 0 or max_duration < min_duration:
        raise ValueError("Expected 0 < min_duration <= max_duration")

    ordered = sorted(words, key=lambda word: (word.start, word.end))
    chunks: list[list[Word]] = []
    current: list[Word] = []
    for word in ordered:
        if current:
            elapsed = word.end - current[0].start
            gap = word.start - current[-1].end
            sentence_end = bool(re.search(r"[.!?][\"')\]]?$", current[-1].text))
            should_split = elapsed >= max_duration or (
                elapsed >= min_duration and (gap >= max_gap or sentence_end)
            )
            if should_split:
                chunks.append(current)
                current = []
        current.append(word)
    if current:
        chunks.append(current)

    result: list[ClipCandidate] = []
    for chunk in chunks:
        start, end = chunk[0].start, chunk[-1].end
        if end - start < min_duration * 0.55:
            # Fold a very short tail into the previous candidate rather than emit noise.
            if result:
                previous = result.pop()
                merged_words = previous.words + tuple(chunk)
                merged_end = merged_words[-1].end
                result.append(
                    ClipCandidate(
                        start=previous.start,
                        end=merged_end,
                        score=previous.score,
                        reason=previous.reason,
                        words=merged_words,
                    )
                )
            else:
                continue
        else:
            result.append(
                ClipCandidate(
                    start=start,
                    end=end,
                    score=0,
                    reason="Not yet scored",
                    words=tuple(chunk),
                )
            )
    return result


def heuristic_score(candidate: ClipCandidate) -> ClipCandidate:
    text = " ".join(word.text for word in candidate.words).lower()
    tokens = re.findall(r"[a-z0-9']+", text)
    if not tokens:
        return ClipCandidate(
            candidate.start, candidate.end, 0, "No transcript text", candidate.words
        )

    unique_ratio = len(set(tokens)) / max(1, len(tokens))
    hook_hits = sum(token in _HOOK_TERMS for token in tokens)
    emotion_hits = sum(token in _EMOTION_TERMS for token in tokens)
    punctuation_hits = sum(word.text.count("!") + word.text.count("?") for word in candidate.words)
    start_words = " ".join(tokens[:12])
    hook_open = any(
        start_words.startswith(term)
        for term in ("why", "how", "here", "this", "the", "i", "you")
    )
    pace = len(tokens) / max(candidate.duration, 1.0)

    score = 38.0
    score += min(18.0, hook_hits * 3.0)
    score += min(14.0, emotion_hits * 3.5)
    score += min(8.0, punctuation_hits * 2.0)
    score += min(8.0, unique_ratio * 8.0)
    score += 5.0 if hook_open else 0.0
    score += 5.0 if 1.6 <= pace <= 3.8 else 0.0
    score = max(0.0, min(100.0, score))

    reasons: list[str] = []
    if hook_hits:
        reasons.append("hook language")
    if emotion_hits:
        reasons.append("emotional wording")
    if punctuation_hits:
        reasons.append("expressive delivery markers")
    if not reasons:
        reasons.append("balanced standalone speech segment")
    return ClipCandidate(
        start=candidate.start,
        end=candidate.end,
        score=round(score, 1),
        reason=", ".join(reasons),
        words=candidate.words,
    )


def _prompt(candidates: list[ClipCandidate]) -> str:
    payload = [
        {
            "id": index,
            "duration_seconds": round(candidate.duration, 2),
            "transcript": " ".join(word.text for word in candidate.words),
        }
        for index, candidate in enumerate(candidates)
    ]
    return (
        "Rank short-form video moments for clarity and viewer value. Score each candidate 0-100 "
        "using an opening hook, emotional or informative payoff, standalone context, and a clean "
        "ending. Do not reward misinformation, outrage bait, or missing context. Return ONLY valid "
        'JSON: {"scores":[{"id":0,"score":0,"reason":"short explanation"}]}. '
        "Use each supplied id once. Never invent timestamps or alter the supplied transcript.\n"
        + json.dumps(payload, ensure_ascii=False)
    )


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    first, last = cleaned.find("{"), cleaned.rfind("}")
    if first < 0 or last < first:
        raise ValueError("LLM response did not contain a JSON object")
    parsed = json.loads(cleaned[first : last + 1])
    if not isinstance(parsed, dict) or not isinstance(parsed.get("scores"), list):
        raise ValueError("LLM JSON must contain a 'scores' array")
    return parsed


@dataclass(slots=True)
class OllamaScorer:
    model: str = "qwen2.5:7b"
    base_url: str = "http://127.0.0.1:11434"
    timeout: float = 120.0

    def score(self, candidates: list[ClipCandidate]) -> list[ClipCandidate]:
        body = json.dumps(
            {
                "model": self.model,
                "stream": False,
                "format": "json",
                "messages": [{"role": "user", "content": _prompt(candidates)}],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.base_url.rstrip("/") + "/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = payload.get("message", {}).get("content", "")
            return _apply_scores(candidates, _extract_json(content))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(f"Ollama moment scoring failed: {exc}") from exc


@dataclass(slots=True)
class OpenAIScorer:
    model: str = "gpt-6-luna"
    api_key: str | None = None
    base_url: str = "https://api.openai.com/v1/responses"
    timeout: float = 90.0

    def score(self, candidates: list[ClipCandidate]) -> list[ClipCandidate]:
        key = self.api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("Set OPENAI_API_KEY to use the OpenAI scorer")
        schema = {
            "type": "object",
            "properties": {
                "scores": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer"},
                            "score": {"type": "number"},
                            "reason": {"type": "string"},
                        },
                        "required": ["id", "score", "reason"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["scores"],
            "additionalProperties": False,
        }
        body = json.dumps(
            {
                "model": self.model,
                "reasoning": {"effort": "low"},
                "input": _prompt(candidates),
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "clip_scores",
                        "strict": True,
                        "schema": schema,
                    }
                },
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.base_url,
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = _responses_text(payload)
            return _apply_scores(candidates, _extract_json(content))
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            KeyError,
            ValueError,
        ) as exc:
            raise RuntimeError(f"OpenAI moment scoring failed: {exc}") from exc


@dataclass(slots=True)
class GeminiScorer:
    model: str = "gemini-3.8-flash"
    api_key: str | None = None
    timeout: float = 90.0

    def score(self, candidates: list[ClipCandidate]) -> list[ClipCandidate]:
        key = self.api_key or os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("Set GEMINI_API_KEY to use the Gemini scorer")
        body = json.dumps(
            {
                "contents": [{"parts": [{"text": _prompt(candidates)}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            }
        ).encode("utf-8")
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            + self.model
            + ":generateContent"
        )
        request = urllib.request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            content = payload["candidates"][0]["content"]["parts"][0]["text"]
            return _apply_scores(candidates, _extract_json(content))
        except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            KeyError,
            ValueError,
        ) as exc:
            raise RuntimeError(f"Gemini moment scoring failed: {exc}") from exc


def _responses_text(payload: dict[str, Any]) -> str:
    """Collect text blocks from the OpenAI Responses API response shape."""
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct:
        return direct
    parts: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str):
                    parts.append(text)
    if not parts:
        raise ValueError("OpenAI Responses API returned no output text")
    return "\n".join(parts)


def _apply_scores(
    candidates: list[ClipCandidate], payload: dict[str, Any]
) -> list[ClipCandidate]:
    indexed: dict[int, tuple[float, str]] = {}
    for item in payload["scores"]:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item["id"])
            score = float(item["score"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= index < len(candidates) and 0 <= score <= 100:
            indexed[index] = (score, str(item.get("reason", "LLM-scored moment"))[:240])

    result: list[ClipCandidate] = []
    for index, candidate in enumerate(candidates):
        score, reason = indexed.get(index, (heuristic_score(candidate).score, "Heuristic fallback"))
        result.append(
            ClipCandidate(
                start=candidate.start,
                end=candidate.end,
                score=round(score, 1),
                reason=reason,
                words=candidate.words,
            )
        )
    return sorted(result, key=lambda item: item.score, reverse=True)


def rank_candidates(
    candidates: list[ClipCandidate], scorer: str = "heuristic", *, model: str | None = None
) -> list[ClipCandidate]:
    if scorer == "heuristic":
        ranked = [heuristic_score(candidate) for candidate in candidates]
        return sorted(ranked, key=lambda item: item.score, reverse=True)
    if scorer == "ollama":
        return OllamaScorer(model=model or "qwen2.5:7b").score(candidates)
    if scorer == "openai":
        return OpenAIScorer(model=model or "gpt-6-luna").score(candidates)
    if scorer == "gemini":
        return GeminiScorer(model=model or "gemini-3.8-flash").score(candidates)
    raise ValueError(f"Unsupported scorer: {scorer}")