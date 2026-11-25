# Release notes

## Stable release

ClipRally provides a local-first video-to-shorts workflow with:

- Local video inspection and optional URL ingestion through yt-dlp.
- Offline word-timestamp transcription with Faster-Whisper.
- Heuristic moment ranking and optional Ollama, OpenAI, or Gemini scoring.
- Vertical FFmpeg rendering, loudness normalization, and word-highlight captions.
- Optional OpenCV face-centred reframing.
- RSS/Atom and YouTube chart discovery.
- Editable offline title and hashtag suggestions with JSON manifests.
- Local browser UI, command-line interface, Python API, and MCP server.
- Explicit YouTube, TikTok, and Instagram publishing adapters.

Current boundaries are documented in the README: face centering is not active-speaker diarization; automatic gameplay/facecam split-screen is not included; discovery does not download or repost content; and live platform behavior depends on third-party APIs, permissions, and account eligibility.