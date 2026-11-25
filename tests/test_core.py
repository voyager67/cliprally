from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest

from cliprally.captions import write_karaoke_ass
from cliprally.ingestion import download_authorized_url
from cliprally.models import ClipCandidate, Word
from cliprally.moments import (
    _apply_scores,
    _extract_json,
    _responses_text,
    build_candidates,
    heuristic_score,
)
from cliprally.pipeline import load_transcript_json
from cliprally.reframe import crop_x_expression
from cliprally.trends import fetch_rss


def _long_words() -> tuple[Word, ...]:
    words = []
    for index in range(70):
        text = ["Actually", "this", "is", "an", "incredible", "idea"][index % 6]
        if index in {29, 59, 69}:
            text += "."
        start = index * 0.5
        words.append(Word(text=text, start=start, end=start + 0.32))
    return tuple(words)


def test_build_candidates_and_heuristic_ranking() -> None:
    candidates = build_candidates(_long_words(), min_duration=12, max_duration=22)
    assert len(candidates) >= 2
    assert all(item.duration <= 22.5 for item in candidates)
    ranked = [heuristic_score(item) for item in candidates]
    assert all(0 <= item.score <= 100 for item in ranked)
    assert all(item.reason != "Not yet scored" for item in ranked)


def test_candidate_validates_score_and_time() -> None:
    with pytest.raises(ValueError):
        ClipCandidate(start=2, end=1, score=20, reason="bad")
    with pytest.raises(ValueError):
        ClipCandidate(start=0, end=1, score=101, reason="bad")
    with pytest.raises(ValueError, match="finite"):
        ClipCandidate(start=float("nan"), end=1, score=20, reason="bad")
    with pytest.raises(ValueError, match="finite"):
        Word(text="bad", start=0, end=float("inf"))


def test_llm_json_and_score_fallback() -> None:
    candidates = [ClipCandidate(0, 20, 0, "pending", (Word("hello", 0, 0.3),))]
    payload = _extract_json('```json\n{"scores":[{"id":0,"score":88,"reason":"good hook"}]}\n```')
    scored = _apply_scores(candidates, payload)
    assert scored[0].score == 88
    assert scored[0].reason == "good hook"


def test_caption_file_sanitizes_ass_override_injection(tmp_path) -> None:
    words = [Word(text=r"{\\an8}Hi", start=0.1, end=0.4), Word(text="there!", start=0.5, end=0.9)]
    path = write_karaoke_ass(words, tmp_path / "subtitles.ass")
    content = path.read_text(encoding="utf-8")
    assert "Dialogue:" in content
    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content
    assert r"{\\an8}" not in content
    assert r"{\kf" in content


def test_crop_expression_clamps_and_interpolates() -> None:
    expression = crop_x_expression(1920, 607.5, [(0.0, 100), (1.0, 1500)])
    assert expression.startswith("max(0,min(in_w-out_w,")
    assert "if(lt(t,1.000)" in expression
    assert crop_x_expression(1920, 600, []) == "(in_w-out_w)/2"


def test_rss_atom_parser() -> None:
    body = b'''<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>Creator update</title><link href="https://example.com/watch"/>
      <published>2026-11-25T12:00:00Z</published></entry></feed>'''

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    with patch("cliprally.trends.urllib.request.urlopen", return_value=FakeResponse(body)):
        items = fetch_rss("https://example.com/feed.xml")
    assert len(items) == 1
    assert items[0].title == "Creator update"
    assert items[0].url == "https://example.com/watch"


def test_url_ingest_requires_rights_before_network_or_optional_import(tmp_path) -> None:
    with pytest.raises(PermissionError):
        download_authorized_url("https://example.com/video", tmp_path, rights_confirmed=False)


def test_load_transcript_json(tmp_path) -> None:
    path = tmp_path / "transcript.json"
    path.write_text(
        json.dumps({"language": "en", "words": [{"text": "Good", "start": 0.1, "end": 0.5}]}),
        encoding="utf-8",
    )
    transcript = load_transcript_json(path)
    assert transcript.language == "en"
    assert transcript.words[0].text == "Good"


def test_rss_rejects_non_http_schemes() -> None:
    with pytest.raises(ValueError, match=r"http\(s\)"):
        fetch_rss("file:///etc/passwd")


def test_rss_requires_positive_limit() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        fetch_rss("https://example.com/feed.xml", limit=0)


def test_openai_responses_text_extraction() -> None:
    payload = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": '{"scores":[]}'}],
            }
        ]
    }
    assert _responses_text(payload) == '{"scores":[]}'


def test_openai_scorer_uses_responses_api_and_structured_output() -> None:
    from cliprally.moments import OpenAIScorer

    candidate = ClipCandidate(0, 20, 0, "pending", (Word("hello", 0, 0.3),))
    response_body = json.dumps(
        {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"scores":[{"id":0,"score":91,"reason":"clear hook"}]}',
                        }
                    ],
                }
            ]
        }
    ).encode()

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode())
        return FakeResponse(response_body)

    with patch("cliprally.moments.urllib.request.urlopen", side_effect=fake_urlopen):
        ranked = OpenAIScorer(api_key="test-key").score([candidate])

    assert captured["url"].endswith("/v1/responses")
    assert captured["body"]["model"] == "gpt-6-luna"
    assert captured["body"]["text"]["format"]["type"] == "json_schema"
    assert ranked[0].score == 91


def test_caption_font_fields_are_sanitized_and_wrapping_enabled(tmp_path) -> None:
    path = write_karaoke_ass(
        [Word("test", 0.0, 0.2)],
        tmp_path / "captions.ass",
        font_name="Arial,evil\nStyle:Bad",
    )
    content = path.read_text(encoding="utf-8")
    assert "WrapStyle: 0" in content
    assert "Arial evil Style:Bad" in content
    with pytest.raises(ValueError, match="font_size"):
        write_karaoke_ass([Word("test", 0.0, 0.2)], tmp_path / "bad.ass", font_size=0)