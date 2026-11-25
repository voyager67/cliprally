# Validation record

This snapshot records the checks performed for the ClipRally 1.0.0 release candidate. It separates automated CI and local tests from optional integrations that have not been live-certified.

## Automated CI

The latest recorded [GitHub Actions CI run](https://github.com/voyager67/cliprally/actions/runs/45680850293) completed successfully on commit `0bf8404`.

- Python matrix: 3.10, 3.11, 3.12, and 3.13.
- FFmpeg and FFprobe installed in the runner.
- Optional OpenCV visual-analysis dependency installed.
- Ruff lint and the pytest suite passed in all four matrix jobs.

## Local checks

Environment used for the local checks:

- Python 3.13.5
- FFmpeg 7.1.5 and FFprobe 7.1.5
- OpenCV 4.13.0

Checks completed:

- `python -m compileall -q src tests` — passed.
- `python -m pytest -q` — 33 tests passed.
- `python -m cliprally check` — passed; FFmpeg and FFprobe were found.
- `python -m cliprally --help` — passed.
- `pip wheel . --no-deps --no-build-isolation` — built the `cliprally 1.0.0` wheel successfully.
- Synthetic-video tests exercised visual-only detection, hybrid candidate generation, and FFmpeg vertical rendering.

## Coverage

- Transcript parsing, timestamp validation, segment selection, heuristic ranking, and optional scorer request/response handling.
- Visual-activity scoring, candidate-window diversity, silent visual-only processing, and hybrid fallback when no speech is detected.
- ASS caption escaping and timing.
- FFmpeg portrait MP4 rendering, including audio, subtitle, and loudness paths.
- End-to-end processing of generated footage with supplied word-timed transcript data.
- Offline title/hashtag suggestions and metadata matching by filename.
- Mocked YouTube, TikTok, and Instagram publisher flows, including privacy and confirmation guards.

## Not live-certified

The following depend on optional packages, external services, user credentials, or hardware that was not exercised in the checks above:

- Faster-Whisper model downloads, real speech-recognition accuracy, and performance across languages, accents, CPUs, and GPUs.
- Streamlit browser UI runtime.
- Live yt-dlp extraction from third-party platforms.
- MCP transport with a live MCP client.
- Live Ollama, OpenAI, or Gemini scoring requests.
- Live YouTube, TikTok, or Meta OAuth, uploads, app review, moderation, and publication.
- CUDA/cuDNN, NVENC, and VideoToolbox acceleration on end-user machines.
- Semantic event recognition for specific gameplay actions, objects, actors, or movie scenes. Current visual analysis is limited to motion and shot-change heuristics.
- Cross-platform smoke testing on representative Windows, macOS, and Linux user machines.

A passing test suite verifies only the behavior exercised by those tests. It does not guarantee that a third-party service, media source, account, or device will accept every request.
