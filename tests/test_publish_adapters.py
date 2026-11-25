from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cliprally.models import Word
from cliprally.metadata import suggest_metadata


def test_suggest_metadata_is_offline_editable_and_unicode_aware() -> None:
    suggestions = suggest_metadata(
        [
            Word("How", 0.0, 0.2),
            Word("creators", 0.2, 0.5),
            Word("build", 0.5, 0.8),
            Word("momentum!", 0.8, 1.2),
            Word("क्रिएटर", 1.3, 1.8),
        ]
    )
    assert suggestions["title"] == "How creators build momentum"
    assert "#shorts" in suggestions["hashtags"]
    assert "#creators" in suggestions["hashtags"]
    assert "#क्रिएटर" in suggestions["hashtags"]
    assert suggestions["method"] == "offline-transcript-heuristic"


def test_suggest_metadata_rejects_unbounded_hashtag_count() -> None:
    with pytest.raises(ValueError, match="max_hashtags"):
        suggest_metadata([Word("test", 0, 0.2)], max_hashtags=21)


def test_tiktok_direct_post_uses_creator_privacy_and_chunk_upload(tmp_path: Path) -> None:
    from cliprally.publish import tiktok

    video = tmp_path / "sample.mp4"
    video.write_bytes(b"small test video payload")
    request_calls: list[tuple[str, dict]] = []

    def fake_json_request(url: str, token: str, payload: dict) -> dict:
        request_calls.append((url, payload))
        if url.endswith("creator_info/query/"):
            return {"data": {"privacy_level_options": ["SELF_ONLY"]}}
        return {"data": {"upload_url": "https://upload.example.test/put", "publish_id": "pub-1"}}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    captured_upload = {}

    def fake_urlopen(request, timeout=0):
        captured_upload["method"] = request.get_method()
        captured_upload["headers"] = request.headers
        captured_upload["body"] = request.data
        return FakeResponse()

    with (
        patch.object(tiktok, "_json_request", side_effect=fake_json_request),
        patch.object(tiktok.urllib.request, "urlopen", side_effect=fake_urlopen),
    ):
        result = tiktok.direct_post_video(
            video, title="Test clip", access_token="test", privacy_level="SELF_ONLY",
            creator_info={"privacy_level_options": ["SELF_ONLY"]}, confirmed=True,
        )

    assert result == "pub-1"
    assert len(request_calls) == 1
    assert captured_upload["method"] == "PUT"
    assert captured_upload["body"] == video.read_bytes()


def test_tiktok_direct_post_rejects_unavailable_privacy(tmp_path: Path) -> None:
    from cliprally.publish import tiktok

    video = tmp_path / "sample.mp4"
    video.write_bytes(b"payload")
    with patch.object(
        tiktok,
        "_json_request",
        return_value={"data": {"privacy_level_options": ["SELF_ONLY"]}},
    ):
        with pytest.raises(ValueError, match="not available"):
            tiktok.direct_post_video(
                video, title="clip", access_token="test", privacy_level="PUBLIC_TO_EVERYONE",
                creator_info={"privacy_level_options": ["SELF_ONLY"]}, confirmed=True,
            )


def test_instagram_reel_publish_state_machine(tmp_path: Path) -> None:
    from cliprally.publish import instagram

    calls: list[tuple[str, str, dict | None]] = []
    responses = [
        {"id": "container-1"},
        {"status_code": "FINISHED", "status": "ok"},
        {"id": "media-1"},
    ]

    def fake_request(method: str, url: str, token: str, data=None):
        calls.append((method, url, data))
        return responses.pop(0)

    with patch.object(instagram, "_request", side_effect=fake_request):
        with patch.object(instagram.time, "sleep"):
            result = instagram.publish_reel(
                "https://cdn.example.test/clip.mp4",
                ig_user_id="user-1",
                access_token="token",
                api_version="v24.0",
            )

    assert result == "media-1"
    assert len(calls) == 3
    assert calls[0][1].endswith("/user-1/media")
    assert calls[1][1].endswith("/container-1?fields=status_code,status")
    assert calls[-1][0] == "POST"
    assert calls[-1][1].endswith("/user-1/media_publish")
    assert calls[-1][2] == {"creation_id": "container-1"}


def test_instagram_rejects_invalid_api_version_before_network() -> None:
    from cliprally.publish.instagram import publish_reel

    with pytest.raises(ValueError, match="API version"):
        publish_reel(
            "https://cdn.example.test/clip.mp4",
            ig_user_id="user",
            access_token="token",
            api_version="../../bad",
        )


def test_instagram_rejects_non_public_video_url() -> None:
    from cliprally.publish.instagram import publish_reel

    with pytest.raises(ValueError, match="public HTTPS"):
        publish_reel(
            "http://127.0.0.1/private.mp4",
            ig_user_id="user",
            access_token="token",
            api_version="v24.0",
        )


def test_load_suggested_metadata_matches_filename(tmp_path: Path) -> None:
    from cliprally.metadata import load_suggested_metadata

    metadata = tmp_path / "metadata.json"
    metadata.write_text(
        '{"clips":[{"file":"01-clip.mp4","title":"A useful clip",'
        '"hashtags":["#shorts","#topic"]}]}',
        encoding="utf-8",
    )
    result = load_suggested_metadata(metadata, tmp_path / "01-clip.mp4")
    assert result == {"title": "A useful clip", "hashtags": ["#shorts", "#topic"]}


def test_tiktok_upload_requires_explicit_confirmation(tmp_path: Path) -> None:
    from cliprally.publish.tiktok import direct_post_video

    video = tmp_path / "sample.mp4"
    video.write_bytes(b"payload")
    with pytest.raises(PermissionError, match="explicit per-post confirmation"):
        direct_post_video(video, title="clip", access_token="token")


def test_youtube_upload_adapter_builds_private_safe_request(tmp_path: Path, monkeypatch) -> None:
    import sys
    import types

    from cliprally.publish.youtube import upload_video

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    secrets = tmp_path / "client-secrets.json"
    secrets.write_text("{}", encoding="utf-8")
    token_file = tmp_path / "oauth-token.json"
    token_file.write_text("{}", encoding="utf-8")
    captured = {}

    class FakeCredentials:
        valid = True
        expired = False
        refresh_token = None

        @classmethod
        def from_authorized_user_file(cls, filename, scopes):
            captured["token_path"] = filename
            captured["scopes"] = scopes
            return cls()

    class FakeMediaFileUpload:
        def __init__(self, filename, **kwargs):
            captured["media_file"] = filename
            captured["media_kwargs"] = kwargs

    class FakeUploadRequest:
        def next_chunk(self):
            return None, {"id": "youtube-video-id"}

    class FakeVideos:
        def insert(self, **kwargs):
            captured["insert"] = kwargs
            return FakeUploadRequest()

    class FakeYoutube:
        def videos(self):
            return FakeVideos()

    def fake_build(service, version, **kwargs):
        captured["build"] = (service, version, kwargs)
        return FakeYoutube()

    modules = {}
    package_names = [
        "google", "google.auth", "google.auth.transport", "google.auth.transport.requests",
        "google.oauth2", "google.oauth2.credentials", "google_auth_oauthlib",
        "google_auth_oauthlib.flow", "googleapiclient", "googleapiclient.discovery",
        "googleapiclient.http",
    ]
    for name in package_names:
        module = types.ModuleType(name)
        module.__path__ = []
        modules[name] = module
    modules["google.auth.transport.requests"].Request = object
    modules["google.oauth2.credentials"].Credentials = FakeCredentials
    modules["google_auth_oauthlib.flow"].InstalledAppFlow = object
    modules["googleapiclient.discovery"].build = fake_build
    modules["googleapiclient.http"].MediaFileUpload = FakeMediaFileUpload

    with monkeypatch.context() as context:
        for name, module in modules.items():
            context.setitem(sys.modules, name, module)
        url = upload_video(
            video,
            title="A useful clip",
            description="#shorts",
            privacy="private",
            client_secrets=secrets,
            token_path=token_file,
        )

    assert url == "https://www.youtube.com/watch?v=youtube-video-id"
    assert captured["insert"]["body"]["status"] == {"privacyStatus": "private"}
    assert "selfDeclaredMadeForKids" not in captured["insert"]["body"]["status"]
    assert captured["insert"]["body"]["snippet"]["title"] == "A useful clip"