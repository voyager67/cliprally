"""TikTok Content Posting API direct-post adapter."""

from __future__ import annotations

import json
import math
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_API = "https://open.tiktokapis.com/v2"
_MIB = 1024 * 1024


def _json_request(url: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"TikTok API request failed: {exc}") from exc
    error = result.get("error", {})
    if error and error.get("code") not in {None, "ok"}:
        raise RuntimeError(f"TikTok API error: {error.get('code')} — {error.get('message', '')}")
    return result


def query_creator_info(*, access_token: str | None = None) -> dict[str, Any]:
    """Fetch the creator profile and currently allowed privacy settings."""
    token = access_token or os.getenv("TIKTOK_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("Set TIKTOK_ACCESS_TOKEN after completing TikTok OAuth")
    response = _json_request(_API + "/post/publish/creator_info/query/", token, {})
    data = response.get("data", {})
    if not isinstance(data, dict) or not data.get("privacy_level_options"):
        raise RuntimeError("TikTok did not return creator publishing permissions")
    return data


def direct_post_video(
    video_path: str | Path,
    *,
    title: str,
    access_token: str | None = None,
    privacy_level: str = "SELF_ONLY",
    disable_comment: bool = False,
    disable_duet: bool = False,
    disable_stitch: bool = False,
    creator_info: dict[str, Any] | None = None,
    confirmed: bool = False,
) -> str:
    """Publish a local MP4 through the officially authorized Direct Post API.

    The TikTok developer app must be approved for `video.publish`, and the user
    must authorize the app. Unaudited apps are limited to private visibility.
    """
    token = access_token or os.getenv("TIKTOK_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("Set TIKTOK_ACCESS_TOKEN after completing TikTok OAuth")
    if not confirmed:
        raise PermissionError(
            "TikTok publishing requires explicit per-post confirmation after reviewing "
            "the creator profile and available privacy settings."
        )
    media = Path(video_path).expanduser().resolve()
    if not media.is_file():
        raise FileNotFoundError(media)
    size = media.stat().st_size
    if size <= 0 or size > 4 * 1024 * 1024 * 1024:
        raise ValueError("TikTok supports video files up to 4 GB")
    mime_type = mimetypes.guess_type(media.name)[0] or "video/mp4"
    if mime_type not in {"video/mp4", "video/quicktime", "video/webm"}:
        raise ValueError("TikTok direct-post adapter supports MP4, MOV, or WebM files")

    creator = creator_info or query_creator_info(access_token=token)
    options = creator.get("privacy_level_options", [])
    if privacy_level not in options:
        raise ValueError(
            f"Privacy level {privacy_level!r} is not available for this account. "
            f"Available values: {', '.join(options) or 'none returned'}"
        )

    if size <= 64 * _MIB:
        chunk_size = size
        chunk_count = 1
    else:
        chunk_count = math.ceil(size / (64 * _MIB))
        chunk_size = math.ceil(size / chunk_count)
    if chunk_count > 1000 or chunk_size > 64 * _MIB:
        raise ValueError("TikTok upload exceeds the supported chunk limits")

    initialized = _json_request(
        _API + "/post/publish/video/init/",
        token,
        {
            "post_info": {
                "title": title[:2200],
                "privacy_level": privacy_level,
                "disable_comment": disable_comment,
                "disable_duet": disable_duet,
                "disable_stitch": disable_stitch,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": size,
                "chunk_size": chunk_size,
                "total_chunk_count": chunk_count,
            },
        },
    )
    data = initialized.get("data", {})
    upload_url = data.get("upload_url")
    publish_id = data.get("publish_id")
    if not upload_url or not publish_id:
        raise RuntimeError("TikTok did not return an upload URL and publish ID")

    with media.open("rb") as handle:
        first = 0
        while first < size:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            last = first + len(chunk) - 1
            upload_request = urllib.request.Request(
                upload_url,
                data=chunk,
                headers={
                    "Content-Type": mime_type,
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {first}-{last}/{size}",
                },
                method="PUT",
            )
            try:
                with urllib.request.urlopen(upload_request, timeout=180) as response:
                    if response.status not in {200, 201, 206}:
                        raise RuntimeError(f"TikTok upload returned HTTP {response.status}")
            except (urllib.error.URLError, TimeoutError) as exc:
                raise RuntimeError(f"TikTok media upload failed: {exc}") from exc
            first = last + 1
    return str(publish_id)