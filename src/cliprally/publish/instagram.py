"""Instagram Reels publishing adapter using the official Graph API flow."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def _request(
    method: str,
    url: str,
    token: str,
    data: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Instagram Graph API request failed: {exc}") from exc
    if "error" in result:
        error = result["error"]
        raise RuntimeError(f"Instagram API error: {error.get('message', 'unknown error')}")
    return result


def publish_reel(
    video_url: str,
    *,
    ig_user_id: str | None = None,
    access_token: str | None = None,
    caption: str = "",
    api_version: str | None = None,
    share_to_feed: bool = True,
    wait_timeout: int = 600,
) -> str:
    """Publish a publicly reachable video URL as an Instagram Reel.

    Instagram's server pulls `video_url`; this adapter intentionally does not upload
    media to a hosting provider. The user must host the rendered clip at a public URL.
    """
    user_id = ig_user_id or os.getenv("INSTAGRAM_USER_ID")
    token = access_token or os.getenv("META_ACCESS_TOKEN")
    version = api_version or os.getenv("META_GRAPH_API_VERSION")
    if not user_id or not token or not version:
        raise RuntimeError(
            "Set INSTAGRAM_USER_ID, META_ACCESS_TOKEN, and META_GRAPH_API_VERSION "
            "after configuring Meta's Instagram publishing permissions"
        )
    if not re.fullmatch(r"v\d+\.\d+", version):
        raise ValueError("Meta Graph API version must look like vNN.NN, for example v24.0")
    parsed = urllib.parse.urlparse(video_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Instagram requires a public HTTPS video URL without embedded credentials")

    base = f"https://graph.facebook.com/{version}"
    container = _request(
        "POST",
        f"{base}/{urllib.parse.quote(user_id, safe='')}/media",
        token,
        {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption[:2200],
            "share_to_feed": str(share_to_feed).lower(),
        },
    )
    container_id = container.get("id")
    if not container_id:
        raise RuntimeError("Instagram did not return a Reel container ID")

    deadline = time.monotonic() + max(10, wait_timeout)
    while time.monotonic() < deadline:
        status = _request(
            "GET",
            f"{base}/{urllib.parse.quote(str(container_id), safe='')}?fields=status_code,status",
            token,
        )
        status_code = status.get("status_code")
        if status_code == "FINISHED":
            break
        if status_code in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Instagram Reel processing failed: {status.get('status')}")
        time.sleep(3)
    else:
        raise TimeoutError("Instagram Reel processing did not finish before the timeout")

    published = _request(
        "POST",
        f"{base}/{urllib.parse.quote(user_id, safe='')}/media_publish",
        token,
        {"creation_id": str(container_id)},
    )
    media_id = published.get("id")
    if not media_id:
        raise RuntimeError("Instagram did not return a published media ID")
    return str(media_id)