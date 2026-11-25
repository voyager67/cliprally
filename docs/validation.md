# Validation record

This record distinguishes local processing paths exercised in this workspace from optional dependencies and live services that were not available here.

## Local environment

- Python 3.13.5
- FFmpeg 7.1.5
- FFprobe 7.1.5
- OpenCV 4.13.0
- Faster-Whisper and Streamlit were not installed in this workspace.

## Checks run

- `python -m compileall -q src tests` — passed.
- `pytest -q` — 33 tests passed, including real FFmpeg rendering and mocked publisher adapter tests.
- `python -m cliprally check` — passed; FFmpeg and FFprobe were found.
- `python -m cliprally --help` and `python -m cliprally clip --help` — passed.
- Built the wheel with `pip wheel . --no-deps --no-build-isolation` — passed.
- Installed the wheel into an isolated target directory; the installed `python -m cliprally check` command passed.
- Ran the CLI processing path against generated source footage and supplied word-timed transcript JSON — produced two 1080×1920 H.264 MP4 clips, captions, `manifest.json`, and `metadata.json`.
- Checked required README links and local-first positioning — passed.
- Clean source archive contents and SHA-256 checksum — generated and checked.

## Covered behavior

- Transcript parsing, input timing validation, segment selection, heuristic ranking, and optional scorer request/response handling.
- Visual activity scoring, candidate-window diversity, silent visual-only processing, hybrid fallback when no speech is detected, and generated test-video sampling (when OpenCV is installed).
- ASS caption escaping and timing.
- Real FFmpeg portrait MP4 creation, including audio/subtitle and loudness paths.
- End-to-end processing of synthetic source footage with supplied word-level transcript timestamps.
- Offline title/hashtag suggestions and metadata matching by filename.
- Mocked YouTube, TikTok, and Instagram publisher request/response flows, including privacy and confirmation guards.

## Not live-certified in this workspace

- Faster-Whisper model download, actual speech recognition accuracy, and performance across languages, accents, CPUs, and GPUs. The optional package could not be installed in this network-restricted workspace.
- Streamlit browser UI runtime. Streamlit was not installed here.
- yt-dlp downloads from live platform URLs. The optional dependency was not installed and each site's extractor and terms may change.
- MCP transport with a live MCP client. The optional MCP package was not installed.
- Live Ollama, OpenAI, or Gemini scoring requests.
- Live YouTube, TikTok, or Meta OAuth, upload, app review, moderation, and publication results.
- CUDA/cuDNN, NVENC, and VideoToolbox acceleration on user machines.
- Semantic event recognition for specific gameplay actions, objects, actors, or movie scenes; current visual analysis is motion and shot-change heuristics only.
- Ruff lint locally. Ruff was not installed and network restrictions prevented fetching it; Ruff remains configured in GitHub Actions.

A passing local suite establishes only the behavior exercised by those tests. It does not guarantee that a third-party service, media source, app, or user account will accept every request. Before public launch, maintainers should also run the optional dependency smoke tests on representative Windows, macOS, and Linux machines.