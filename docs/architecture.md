# Architecture

ClipRally is a local-first Python pipeline. Local files are the primary input, and hosted APIs are optional integrations rather than prerequisites for editing.

```text
Local video / authorized URL
           │
           ▼
      FFprobe validation
           │
           ▼
  Faster-Whisper word timestamps
           │
           ▼
  Candidate segment construction
           │
           ▼
 Heuristic / Ollama / OpenAI / Gemini ranking
           │
           ▼
 Optional OpenCV face-centred crop
           │
           ▼
 ASS karaoke captions + FFmpeg 9:16 render
           │
           ▼
 MP4 clips + metadata.json + manifest.json
           │
           └──── separate, explicit publisher commands
                  YouTube / TikTok / Instagram
```

## Components

- `media.py`: FFprobe inspection and FFmpeg binary discovery.
- `ingestion.py`: optional yt-dlp downloader with HTTP(S)-only URLs, a rights confirmation, an isolated output directory, and a timeout.
- `transcription.py`: local Faster-Whisper word timestamps.
- `moments.py`: candidate segmentation, local heuristic ranking, and optional LLM scoring.
- `reframe.py`: sampled OpenCV face-centering heuristic. It is not speaker diarization.
- `captions.py`: safe ASS subtitle generation with word-level karaoke timing.
- `render.py`: portrait crop, caption burn-in, audio normalization, and MP4 encoding.
- `metadata.py`: offline editable title and hashtag suggestions.
- `trends.py`: RSS/Atom feeds and the API-backed YouTube `mostPopular` chart.
- `publish/`: independent official API adapters. Publishing is never part of the clip pipeline.
- `ui_app.py`: optional Streamlit browser interface intended for localhost.
- `mcp_server.py`: optional local MCP server for media inspection and clipping.

## Trust boundaries

- Local heuristic ranking, local transcription, and rendering keep media on the user's machine.
- Choosing OpenAI or Gemini sends candidate transcript text to that provider.
- URL fetching contacts the user-supplied site through yt-dlp. It does not bypass DRM, private access, or paywalls.
- Trend discovery returns links for review; it does not claim that reuse is authorized.
- Publisher adapters send media or a hosted media URL only when invoked explicitly. Platform credentials, approvals, and account eligibility remain user responsibilities.
- The local UI and MCP server have the same filesystem access as the user running them; do not expose them to untrusted networks or clients.