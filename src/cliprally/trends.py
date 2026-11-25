"""Low-friction RSS and optional YouTube public-chart discovery."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TrendItem:
    title: str
    url: str
    source: str
    published: str | None = None


def fetch_rss(feed_url: str, *, timeout: float = 20.0, limit: int = 20) -> list[TrendItem]:
    parsed_url = urllib.parse.urlparse(feed_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("RSS/Atom feeds must use a valid http(s) URL")
    if limit < 1:
        raise ValueError("limit must be at least 1")
    request = urllib.request.Request(
        feed_url,
        headers={"User-Agent": "ClipRally/1.0 (+https://github.com/voyager67/cliprally)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            xml_data = response.read(5_000_000)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not read RSS/Atom feed: {exc}") from exc

    root = ET.fromstring(xml_data)
    source = feed_url
    items: list[TrendItem] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1].lower()
        if tag not in {"item", "entry"}:
            continue
        title = ""
        link = ""
        published = None
        for child in element:
            child_tag = child.tag.rsplit("}", 1)[-1].lower()
            if child_tag == "title" and child.text:
                title = child.text.strip()
            elif child_tag == "link":
                link = child.attrib.get("href", "") or (child.text or "").strip()
            elif child_tag in {"pubdate", "published", "updated"} and child.text:
                published = child.text.strip()
        if title and link:
            items.append(TrendItem(title=title, url=link, source=source, published=published))
        if len(items) >= limit:
            break
    return items


def youtube_most_popular(
    *, region: str = "US", category: str | None = None, api_key: str | None = None, limit: int = 20
) -> list[TrendItem]:
    key = api_key or os.getenv("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError("Set YOUTUBE_API_KEY to query YouTube's mostPopular chart")
    params = {
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": region,
        "maxResults": str(max(1, min(limit, 50))),
        "key": key,
    }
    if category:
        params["videoCategoryId"] = category
    url = "https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "ClipRally/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"YouTube chart request failed: {exc}") from exc

    results: list[TrendItem] = []
    for item in payload.get("items", []):
        video_id = item.get("id")
        snippet = item.get("snippet", {})
        if video_id and snippet.get("title"):
            results.append(
                TrendItem(
                    title=str(snippet["title"]),
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    source="YouTube mostPopular",
                    published=snippet.get("publishedAt"),
                )
            )
    return results