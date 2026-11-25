"""Offline title and hashtag suggestions for generated clips."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

from .models import Word

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "can", "could",
    "did", "do", "does", "for", "from", "had", "has", "have", "he", "her", "hers",
    "him", "his", "how", "i", "if", "in", "into", "is", "it", "its", "just", "me",
    "my", "of", "on", "or", "our", "ours", "she", "so", "that", "the", "their",
    "them", "there", "these", "they", "this", "those", "to", "too", "us", "was", "we",
    "were", "what", "when", "where", "which", "who", "why", "will", "with", "would",
    "you", "your", "yours", "um", "uh", "yeah", "okay", "ok",
}


def _unicode_tokens(value: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    for character in value:
        category = unicodedata.category(character)
        if category.startswith(("L", "N")) or (category.startswith("M") and current):
            current.append(character)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


def suggest_metadata(
    words: tuple[Word, ...] | list[Word], *, max_hashtags: int = 8
) -> dict[str, object]:
    """Create conservative, offline metadata suggestions from a clip transcript.

    These are editable suggestions, not LLM-generated claims or guaranteed growth tactics.
    Unicode letters are preserved so non-English topics can be represented in hashtags.
    """
    if not 0 <= max_hashtags <= 20:
        raise ValueError("max_hashtags must be between 0 and 20")

    transcript = " ".join(word.text.strip() for word in words if word.text.strip())
    transcript = re.sub(r"\s+", " ", transcript).strip()
    if not transcript:
        title = "A moment worth sharing"
    else:
        first_sentence = re.split(r"(?<=[.!?])\s+", transcript, maxsplit=1)[0]
        title_source = first_sentence if len(first_sentence) >= 12 else transcript
        title = re.sub(r"\s+", " ", title_source).strip(" \t\r\n.!?—-\"'")
        if len(title) > 92:
            shortened = title[:89].rsplit(" ", 1)[0]
            title = (shortened or title[:89]).rstrip(" ,;:-") + "…"
        if not title:
            title = "A moment worth sharing"

    tokens = [token.lower() for token in _unicode_tokens(transcript)]
    keywords = [token for token in tokens if len(token) >= 3 and token not in _STOPWORDS]
    counts = Counter(keywords)
    first_seen: dict[str, int] = {}
    for index, token in enumerate(keywords):
        first_seen.setdefault(token, index)
    ranked = sorted(counts, key=lambda token: (-counts[token], first_seen[token], token))

    hashtags = ["#shorts"]
    for token in ranked:
        normalized = token
        if not normalized or normalized in {item[1:].lower() for item in hashtags}:
            continue
        hashtags.append(f"#{normalized}")
        if len(hashtags) >= max_hashtags:
            break
    return {
        "title": title[:100],
        "hashtags": hashtags[:max_hashtags] if max_hashtags else [],
        "method": "offline-transcript-heuristic",
    }


def load_suggested_metadata(metadata_path: str | Path, video_path: str | Path) -> dict[str, object]:
    """Load the generated metadata entry matching a rendered video filename."""
    path = Path(metadata_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Metadata file does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    clips = payload.get("clips") if isinstance(payload, dict) else None
    if not isinstance(clips, list):
        raise ValueError("Metadata JSON must contain a 'clips' array")
    filename = Path(video_path).name
    for item in clips:
        if isinstance(item, dict) and item.get("file") == filename:
            title = item.get("title")
            hashtags = item.get("hashtags", [])
            if not isinstance(title, str) or not title.strip():
                raise ValueError(f"No valid title suggestion for {filename}")
            if not isinstance(hashtags, list) or any(not isinstance(tag, str) for tag in hashtags):
                raise ValueError(f"Invalid hashtag suggestions for {filename}")
            return {"title": title.strip(), "hashtags": hashtags}
    raise ValueError(f"No metadata entry found for {filename}")