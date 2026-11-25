"""Optional URL ingestion. Local files remain the default and most reliable path."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from .media import MediaError, require_binary

_ALLOWED_SCHEMES = {"http", "https"}


def download_authorized_url(
    url: str,
    output_dir: str | Path,
    *,
    rights_confirmed: bool,
    timeout: float = 1800.0,
) -> Path:
    """Download a URL with yt-dlp after an explicit rights/permission confirmation.

    This deliberately does not provide cookie extraction, DRM workarounds, or private
    content access. Availability depends on the site's rules and yt-dlp's current extractors.
    """
    if not rights_confirmed:
        raise PermissionError(
            "URL downloads require --i-have-rights: only download content you own or are "
            "authorized to use, and follow the source platform's terms."
        )
    parsed = urlparse(url)
    if (
        parsed.scheme not in _ALLOWED_SCHEMES
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Provide a valid http(s) URL without embedded credentials")
    if re.search(r"\s", url):
        raise ValueError("URL must not contain whitespace")
    if timeout <= 0:
        raise ValueError("timeout must be positive")

    try:
        import yt_dlp  # noqa: F401  # checked lazily so the core has no mandatory dependency
    except ImportError as exc:
        raise MediaError(
            "URL ingestion is optional. Install it with: pip install 'cliprally[url-ingest]'"
        ) from exc

    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    # Each fetch gets an isolated output directory so stale files from a previous
    # failed or cancelled download can never be mistaken for the new source.
    fetch_dir = Path(tempfile.mkdtemp(prefix="ingest-", dir=destination))
    template = str(fetch_dir / "source.%(ext)s")
    # yt-dlp uses FFmpeg when it needs to merge separate audio/video streams.
    require_binary("ffmpeg")
    executable = shutil.which("yt-dlp")
    if executable:
        command = [executable]
    else:
        # Support the optional module even when its console script is not on PATH.
        import sys

        command = [sys.executable, "-m", "yt_dlp"]
    command += [
        "--no-playlist",
        "--no-warnings",
        "--restrict-filenames",
        "-f",
        "bv*+ba/b",
        "--merge-output-format",
        "mp4",
        "-o",
        template,
        url,
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError(
            f"URL download exceeded the {timeout:g}-second timeout; partial files were left in "
            f"{fetch_dir} for inspection."
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise MediaError(
            "yt-dlp could not fetch this URL. The site may block downloads, require a supported "
            "login flow, have changed its format, or prohibit the action. "
            "No bypass was attempted.\n"
            + detail[-2000:]
        )

    candidates = sorted(fetch_dir.glob("source.*"), key=lambda item: item.stat().st_mtime)
    if not candidates:
        raise MediaError("yt-dlp reported success but no output media file was found")
    return candidates[-1]