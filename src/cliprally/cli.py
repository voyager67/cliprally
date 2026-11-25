"""Command-line interface for ClipRally."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import __version__
from .media import MediaError, require_binary
from .metadata import load_suggested_metadata
from .pipeline import process_video
from .trends import fetch_rss, youtube_most_popular


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cliprally",
        description="Local-first AI video clipper: long video in, vertical Shorts out.",
    )
    parser.add_argument("--version", action="version", version=f"ClipRally {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    clip = commands.add_parser(
        "clip", help="Create vertical clips from a local video or authorized URL"
    )
    source = clip.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--input", type=Path, help="Local video file (recommended; no API required)"
    )
    source.add_argument(
        "--url", help="A supported public video URL; requires explicit rights confirmation"
    )
    clip.add_argument("--output", type=Path, default=Path("cliprally-output"))
    clip.add_argument("--clips", type=int, default=3, help="Number of top-ranked clips to render")
    clip.add_argument(
        "--model-size",
        default="small",
        help="faster-whisper model: tiny/base/small/medium/large-v3",
    )
    clip.add_argument("--device", default="auto", help="faster-whisper device: auto/cpu/cuda")
    clip.add_argument("--compute-type", default="int8", help="faster-whisper compute type")
    clip.add_argument("--language", default=None, help="Optional language code, e.g. en, hi, mr")
    clip.add_argument(
        "--scorer",
        choices=["heuristic", "ollama", "openai", "gemini"],
        default="heuristic",
    )
    clip.add_argument(
        "--scorer-model", default=None, help="Optional Ollama/OpenAI/Gemini model override"
    )
    clip.add_argument("--min-duration", type=float, default=15.0)
    clip.add_argument("--max-duration", type=float, default=55.0)
    clip.add_argument(
        "--moment-mode",
        choices=["transcript", "hybrid", "visual"],
        default="transcript",
        help=(
            "transcript ranks speech only; hybrid blends speech with visual activity; "
            "visual finds motion/shot-change windows without transcription"
        ),
    )
    clip.add_argument(
        "--visual-sample-interval",
        type=float,
        default=1.5,
        help="Seconds between sampled frames in hybrid/visual mode (minimum 0.25)",
    )
    clip.add_argument("--no-captions", action="store_true", help="Export clips without subtitles")
    clip.add_argument(
        "--face-tracking",
        action="store_true",
        help="Center the crop on detected faces (requires the face-tracking extra)",
    )
    clip.add_argument(
        "--encoder",
        choices=["libx264", "h264_nvenc", "h264_videotoolbox"],
        default="libx264",
    )
    clip.add_argument(
        "--transcript-json", type=Path, help="Use word-timed JSON instead of running Whisper"
    )
    clip.add_argument(
        "--i-have-rights",
        action="store_true",
        help="Confirm you own or are authorized to use URL media",
    )

    trends = commands.add_parser(
        "trends", help="List feed/chart candidates; does not download or repost media"
    )
    trends.add_argument(
        "--feed", action="append", default=[], help="RSS/Atom feed URL; may be repeated"
    )
    trends.add_argument(
        "--youtube-region",
        default=None,
        help="Query YouTube mostPopular, e.g. IN (requires API key)",
    )
    trends.add_argument(
        "--youtube-category", default=None, help="Optional YouTube video category ID"
    )
    trends.add_argument("--limit", type=int, default=20)
    trends.add_argument("--json", action="store_true", help="Print JSON output")

    commands.add_parser("check", help="Check FFmpeg and FFprobe availability")

    yt = commands.add_parser(
        "publish-youtube", help="Upload a clip using official YouTube OAuth/API"
    )
    yt.add_argument("--video", type=Path, required=True)
    yt.add_argument("--title", default=None)
    yt.add_argument("--description", default="")
    yt.add_argument(
        "--metadata", type=Path, default=None,
        help="Use generated metadata.json for title and hashtags",
    )
    yt.add_argument("--client-secrets", type=Path, required=True)
    yt.add_argument("--token-path", type=Path, default=None)
    yt.add_argument("--privacy", choices=["private", "unlisted", "public"], default="private")
    yt.add_argument("--i-have-rights", action="store_true", required=True)

    tt = commands.add_parser(
        "publish-tiktok", help="Direct-post a clip using TikTok Content Posting API"
    )
    tt.add_argument("--video", type=Path, required=True)
    tt.add_argument("--title", default=None)
    tt.add_argument(
        "--metadata", type=Path, default=None,
        help="Use generated metadata.json for title and hashtags",
    )
    tt.add_argument(
        "--privacy",
        choices=["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "SELF_ONLY"],
        default="SELF_ONLY",
    )
    tt.add_argument("--i-have-rights", action="store_true", required=True)
    tt.add_argument("--disable-comments", action="store_true")
    tt.add_argument("--disable-duet", action="store_true")
    tt.add_argument("--disable-stitch", action="store_true")
    tt.add_argument(
        "--confirm-upload",
        action="store_true",
        help="Confirm this video should be sent to TikTok after the creator/privacy review",
    )

    ig = commands.add_parser(
        "publish-instagram", help="Publish a hosted video URL as an Instagram Reel"
    )
    ig.add_argument(
        "--video-url",
        required=True,
        help="Public HTTPS URL; Instagram pulls the media from this URL",
    )
    ig.add_argument("--caption", default=None)
    ig.add_argument(
        "--metadata", type=Path, default=None,
        help="Use generated metadata.json for caption and hashtags; URL basename must match",
    )
    ig.add_argument(
        "--api-version", required=True, help="Meta Graph API version configured for your app"
    )
    ig.add_argument("--i-have-rights", action="store_true", required=True)
    ig.add_argument(
        "--hide-from-feed",
        action="store_true",
        help="Publish the Reel without sharing it to the Instagram feed",
    )

    return parser


def _run_clip(args: argparse.Namespace) -> int:
    source_path = args.input
    if args.url:
        from .ingestion import download_authorized_url

        if not args.i_have_rights:
            raise PermissionError("URL ingestion requires --i-have-rights")
        source_path = download_authorized_url(
            args.url,
            args.output / "source",
            rights_confirmed=args.i_have_rights,
        )

    if args.clips < 1:
        raise ValueError("--clips must be at least 1")
    if args.min_duration <= 0 or args.max_duration < args.min_duration:
        raise ValueError("Expected 0 < --min-duration <= --max-duration")

    manifest = process_video(
        source_path,
        args.output,
        clips=max(1, args.clips),
        model_size=args.model_size,
        device=args.device,
        compute_type=args.compute_type,
        language=args.language,
        scorer=args.scorer,
        scorer_model=args.scorer_model,
        min_duration=args.min_duration,
        max_duration=args.max_duration,
        captions=not args.no_captions,
        face_tracking=args.face_tracking,
        encoder=args.encoder,
        transcript_json=args.transcript_json,
        moment_mode=args.moment_mode,
        visual_sample_interval=args.visual_sample_interval,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


def _run_trends(args: argparse.Namespace) -> int:
    if args.limit < 1:
        raise ValueError("--limit must be at least 1")
    items = []
    for feed in args.feed:
        items.extend(fetch_rss(feed, limit=args.limit))
    if args.youtube_region:
        items.extend(
            youtube_most_popular(
                region=args.youtube_region,
                category=args.youtube_category,
                limit=args.limit,
            )
        )
    items = items[: args.limit]
    serializable = [item.__dict__ if hasattr(item, "__dict__") else {
        "title": item.title, "url": item.url, "source": item.source, "published": item.published
    } for item in items]
    if args.json:
        print(json.dumps(serializable, indent=2, ensure_ascii=False))
    else:
        if not serializable:
            print("No trend items found. Add one or more --feed URLs or --youtube-region IN.")
        for index, item in enumerate(serializable, start=1):
            print(f"{index:02d}. {item['title']}\n    {item['url']}\n    Source: {item['source']}")
    return 0


def _post_metadata(video: Path, metadata_path: Path | None) -> dict[str, object]:
    return load_suggested_metadata(metadata_path, video) if metadata_path else {}


def _with_hashtags(text: str, metadata: dict[str, object]) -> str:
    tags = metadata.get("hashtags", [])
    if not isinstance(tags, list):
        return text
    missing = [tag for tag in tags if isinstance(tag, str) and tag not in text]
    return (text.strip() + (" " + " ".join(missing) if missing else "")).strip()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "clip":
            return _run_clip(args)
        if args.command == "trends":
            return _run_trends(args)
        if args.command == "check":
            print(f"ClipRally {__version__}")
            print(f"FFmpeg: {require_binary('ffmpeg')}")
            print(f"FFprobe: {require_binary('ffprobe')}")
            return 0
        if args.command == "publish-youtube":
            from .publish.youtube import upload_video

            suggestion = _post_metadata(args.video, args.metadata)
            title = args.title or suggestion.get("title")
            if not isinstance(title, str) or not title.strip():
                raise ValueError("Provide --title or --metadata with a title for this video")
            description = _with_hashtags(args.description, suggestion)
            url = upload_video(
                args.video,
                title=title,
                description=description,
                privacy=args.privacy,
                client_secrets=args.client_secrets,
                token_path=args.token_path,
            )
            print(url)
            return 0
        if args.command == "publish-tiktok":
            from .publish.tiktok import direct_post_video, query_creator_info

            suggestion = _post_metadata(args.video, args.metadata)
            title = args.title or suggestion.get("title")
            if not isinstance(title, str) or not title.strip():
                raise ValueError("Provide --title or --metadata with a title for this video")
            title = _with_hashtags(title, suggestion)
            creator = query_creator_info()
            username = creator.get("creator_username", "authorized creator")
            nickname = creator.get("creator_nickname", username)
            options = creator.get("privacy_level_options", [])
            from .media import probe_media

            media_info = probe_media(args.video)
            max_duration = creator.get("max_video_post_duration_sec")
            if isinstance(max_duration, (int, float)) and media_info.duration > max_duration:
                raise ValueError(
                    f"This video is {media_info.duration:.1f}s, but the authorized creator "
                    f"account allows at most {max_duration}s per post."
                )
            print(f"TikTok destination: {nickname} (@{username})")
            print(f"Video duration: {media_info.duration:.1f}s")
            print(f"Title: {title}")
            print(f"Available privacy settings: {', '.join(options)}")
            print(
                "Creator restrictions — "
                f"comments disabled: {bool(creator.get('comment_disabled', False))}, "
                f"duets disabled: {bool(creator.get('duet_disabled', False))}, "
                f"stitches disabled: {bool(creator.get('stitch_disabled', False))}"
            )
            if args.privacy not in options:
                raise ValueError(
                    f"Privacy level {args.privacy!r} is not available for this account."
                )
            if not args.confirm_upload:
                try:
                    confirmation = input(
                        f"Upload {args.video} to @{username} with {args.privacy} visibility? "
                        f"Title: {title}. Type UPLOAD to continue: "
                    )
                except EOFError:
                    raise PermissionError(
                        "No interactive confirmation was available; rerun with "
                        "--confirm-upload after reviewing the destination and privacy setting"
                    ) from None
                if confirmation.strip() != "UPLOAD":
                    print("Upload cancelled.")
                    return 1
            publish_id = direct_post_video(
                args.video,
                title=title,
                privacy_level=args.privacy,
                creator_info=creator,
                disable_comment=(
                    args.disable_comments or bool(creator.get("comment_disabled", False))
                ),
                disable_duet=args.disable_duet or bool(creator.get("duet_disabled", False)),
                disable_stitch=args.disable_stitch or bool(creator.get("stitch_disabled", False)),
                confirmed=True,
            )
            print(f"TikTok publish ID: {publish_id}")
            return 0
        if args.command == "publish-instagram":
            from .publish.instagram import publish_reel

            video_name = unquote(Path(urlparse(args.video_url).path).name)
            suggestion = _post_metadata(Path(video_name), args.metadata) if args.metadata else {}
            caption = args.caption if args.caption is not None else suggestion.get("title", "")
            if not isinstance(caption, str):
                raise ValueError("Caption must be text")
            caption = _with_hashtags(caption, suggestion)
            media_id = publish_reel(
                args.video_url,
                caption=caption,
                api_version=args.api_version,
                share_to_feed=not args.hide_from_feed,
            )
            print(f"Instagram media ID: {media_id}")
            return 0
    except (
        MediaError,
        RuntimeError,
        ValueError,
        PermissionError,
        FileNotFoundError,
        TimeoutError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0