"""Word-timed ASS karaoke subtitle generation."""

from __future__ import annotations

import re
from pathlib import Path

from .models import Word


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, fraction = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{fraction:02d}"


def _safe_ass_text(text: str) -> str:
    # ASS braces introduce override tags. Remove them rather than letting transcript
    # text inject styling or positioning directives into the subtitle file.
    cleaned = text.replace("{", "(").replace("}", ")").replace("\\", "")
    return re.sub(r"\s+", " ", cleaned).strip()


def write_karaoke_ass(
    words: tuple[Word, ...] | list[Word],
    destination: str | Path,
    *,
    words_per_line: int = 5,
    font_name: str = "Arial",
    font_size: int = 58,
) -> Path:
    if words_per_line < 1:
        raise ValueError("words_per_line must be at least 1")

    sorted_words = sorted(words, key=lambda word: word.start)
    if not 8 <= font_size <= 160:
        raise ValueError("font_size must be between 8 and 160")
    safe_font_name = re.sub(r"[,\r\n]", " ", font_name).strip() or "Arial"
    header = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 1080",
            "PlayResY: 1920",
            "LayoutResX: 1080",
            "LayoutResY: 1920",
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            "YCbCr Matrix: TV.709",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Default,{safe_font_name},{font_size},&H00FFFFFF,&H0000D7FF,"
            "&H00101010,&H64000000,-1,0,0,0,100,100,0,0,1,3,1,2,70,70,150,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )
    lines: list[str] = [header]
    for offset in range(0, len(sorted_words), words_per_line):
        group = sorted_words[offset : offset + words_per_line]
        if not group:
            continue
        event_start = group[0].start
        event_end = max(group[-1].end, group[0].start + 0.12)
        tokens: list[str] = []
        for index, word in enumerate(group):
            if index + 1 < len(group):
                duration = max(0.08, group[index + 1].start - word.start)
            else:
                duration = max(0.08, word.end - word.start)
            centiseconds = max(1, round(duration * 100))
            tokens.append(r"{\kf" + str(centiseconds) + "}" + _safe_ass_text(word.text))
        text = " ".join(token for token in tokens if token.strip())
        lines.append(
            f"Dialogue: 0,{_ass_time(event_start)},{_ass_time(event_end)},Default,,0,0,0,,{text}"
        )

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target