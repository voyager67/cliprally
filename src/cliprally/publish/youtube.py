"""Optional YouTube upload adapter using the official YouTube Data API client."""

from __future__ import annotations

from pathlib import Path


def upload_video(
    video_path: str | Path,
    *,
    title: str,
    description: str = "",
    privacy: str = "private",
    client_secrets: str | Path,
    token_path: str | Path | None = None,
) -> str:
    if privacy not in {"private", "unlisted", "public"}:
        raise ValueError("privacy must be private, unlisted, or public")
    media_path = Path(video_path).expanduser().resolve()
    if not media_path.is_file():
        raise FileNotFoundError(media_path)
    secrets_path = Path(client_secrets).expanduser().resolve()
    if not secrets_path.is_file():
        raise FileNotFoundError(secrets_path)

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise RuntimeError(
            "YouTube publishing is optional. Install it with: "
            "pip install 'cliprally[youtube-publish]'"
        ) from exc

    scopes = ["https://www.googleapis.com/auth/youtube.upload"]
    token_file = (
        Path(token_path).expanduser().resolve()
        if token_path
        else Path.home() / ".config" / "cliprally" / "youtube-token.json"
    )
    token_file.parent.mkdir(parents=True, exist_ok=True)
    credentials = None
    if token_file.is_file():
        credentials = Credentials.from_authorized_user_file(str(token_file), scopes)
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), scopes)
            credentials = flow.run_local_server(port=0)
        token_file.write_text(credentials.to_json(), encoding="utf-8")
        try:
            token_file.chmod(0o600)
        except OSError:
            pass

    youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    request = youtube.videos().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "categoryId": "22",
            },
            # Do not set selfDeclaredMadeForKids on the user's behalf; it is a
            # content classification that must be chosen by the channel owner.
            "status": {"privacyStatus": privacy},
        },
        media_body=MediaFileUpload(str(media_path), chunksize=8 * 1024 * 1024, resumable=True),
    )
    response = None
    while response is None:
        _status, response = request.next_chunk()
    video_id = response.get("id")
    if not video_id:
        raise RuntimeError("YouTube API upload completed without returning a video id")
    return f"https://www.youtube.com/watch?v={video_id}"