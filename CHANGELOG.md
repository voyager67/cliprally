# Changelog

All notable changes to ClipRally are documented here.

## 1.0.0

### Added

- Local-first processing for video files, with optional URL ingestion for media users are authorized to download and edit.
- Optional Faster-Whisper transcription with word-level timestamps and heuristic moment ranking.
- Optional Ollama, OpenAI, and Gemini scoring integrations.
- OpenCV visual-activity analysis using optical flow and shot-change heuristics, with transcript-only, hybrid, and visual-only detection modes.
- FFmpeg rendering of vertical 9:16 clips, including audio normalization and word-highlight captions.
- Optional face-centred reframing, local browser UI, command-line interface, Python API, and MCP server.
- RSS/Atom and YouTube chart discovery, editable title and hashtag suggestions, and JSON export manifests.
- Optional YouTube, TikTok, and Instagram publishing adapters that require user-configured credentials and explicit publishing actions.

### Important limitations

- Visual analysis measures motion and shot changes; it does not identify semantic gameplay events, objects, actors, or named film scenes.
- Face-centred reframing is not active-speaker tracking, and automatic gameplay/facecam split-screen is not included.
- Third-party publishing and discovery behavior depends on platform APIs, permissions, account eligibility, and current terms.
- ClipRally does not grant rights to media or guarantee reach, engagement, or virality.
