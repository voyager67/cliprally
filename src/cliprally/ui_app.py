"""Optional local Streamlit interface for ClipRally."""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

import streamlit as st

from cliprally.pipeline import process_video

st.set_page_config(page_title="ClipRally", page_icon="🎬", layout="wide")
st.title("🎬 ClipRally")
st.caption(
    "Turn a video you are authorized to edit into ranked, captioned vertical clips — locally."
)

with st.sidebar:
    st.header("Clip settings")
    clip_count = st.slider("Number of clips", min_value=1, max_value=10, value=3)
    model_size = st.selectbox(
        "Whisper model", ["tiny", "base", "small", "medium", "large-v3"], index=2
    )
    device = st.selectbox("Compute device", ["auto", "cpu", "cuda"], index=0)
    compute_type = st.selectbox("Compute type", ["int8", "float16", "float32"], index=0)
    moment_mode = st.selectbox(
        "How should ClipRally find moments?",
        ["hybrid", "transcript", "visual"],
        format_func={
            "hybrid": "Hybrid — speech + visual activity (recommended)",
            "transcript": "Speech / transcript only",
            "visual": "Visual activity only — no transcription",
        }.get,
        help=(
            "Visual analysis measures motion and shot changes. It can surface action-heavy "
            "gameplay, but it does not identify specific objects or game events yet. "
            "Requires the visual-analysis extra."
        ),
    )
    scorer = st.selectbox("Transcript ranking", ["heuristic", "ollama", "openai", "gemini"])
    scorer_model = st.text_input("Model override (optional)", value="")
    visual_sample_interval = st.select_slider(
        "Visual sampling interval",
        options=[0.5, 1.0, 1.5, 2.0, 3.0],
        value=1.5,
        help="Smaller intervals can catch faster changes but take longer to analyse.",
    )
    language = st.text_input("Language code (optional)", value="", placeholder="en, hi, mr…")
    min_duration = st.slider("Minimum clip length (seconds)", 5, 45, 15)
    max_duration = st.slider(
        "Maximum clip length (seconds)", min_duration + 1, 90, max(55, min_duration + 1)
    )
    captions = st.checkbox("Burn in word-highlight captions", value=True)
    face_tracking = st.checkbox("Face-centred crop (best-effort)", value=False)

input_mode = st.radio(
    "Video source", ["Choose a local file path", "Upload a file"], horizontal=True
)
uploaded = None
local_path = ""
if input_mode == "Upload a file":
    uploaded = st.file_uploader(
        "Choose a video file",
        type=["mp4", "mov", "mkv", "webm", "m4v", "avi"],
        help="Large files are easier to process by choosing their local path instead.",
    )
else:
    local_path = st.text_input(
        "Path to a video on this computer",
        placeholder=r"C:\Videos\interview.mp4 or /home/user/Videos/interview.mp4",
    )
rights_confirmed = st.checkbox(
    "I own this media or have permission to edit it and use the resulting clips."
)

source_ready = uploaded is not None if input_mode == "Upload a file" else bool(local_path.strip())
if st.button("Create my clips", type="primary", disabled=not source_ready):
    if not rights_confirmed:
        st.error("Confirm that you are authorized to edit this media before processing it.")
    elif not source_ready:
        st.error("Choose a video or enter a valid local path first.")
    else:
        previous_workspace = st.session_state.get("cliprally_workspace")
        if previous_workspace:
            shutil.rmtree(previous_workspace, ignore_errors=True)
        st.session_state.pop("cliprally_manifest", None)
        st.session_state.pop("cliprally_workspace", None)
        workspace = Path(tempfile.mkdtemp(prefix="cliprally-ui-"))
        st.session_state["cliprally_workspace"] = str(workspace)
        if input_mode == "Upload a file":
            safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(uploaded.name).name).strip("._")
            if not safe_name:
                safe_name = "source-video.mp4"
            source_path = workspace / safe_name
            source_path.write_bytes(uploaded.getbuffer())
        else:
            source_path = Path(local_path).expanduser().resolve()
            if not source_path.is_file():
                st.error(f"Local video file does not exist: {source_path}")
                st.stop()
        output_path = workspace / "clips"
        try:
            with st.spinner("Analysing the video, finding moments, and rendering clips locally…"):
                manifest = process_video(
                    source_path,
                    output_path,
                    clips=clip_count,
                    model_size=model_size,
                    device=device,
                    compute_type=compute_type,
                    language=language.strip() or None,
                    scorer=scorer,
                    scorer_model=scorer_model.strip() or None,
                    moment_mode=moment_mode,
                    visual_sample_interval=float(visual_sample_interval),
                    min_duration=float(min_duration),
                    max_duration=float(max_duration),
                    captions=captions,
                    face_tracking=face_tracking,
                )
            st.session_state["cliprally_manifest"] = manifest
            st.session_state["cliprally_workspace"] = str(workspace)
            st.success(f"Created {len(manifest['clips'])} clips.")
        except Exception as exc:  # surfaced as actionable UI feedback, not hidden
            st.error(f"ClipRally could not finish this video: {exc}")

manifest = st.session_state.get("cliprally_manifest")
if manifest:
    st.subheader("Your clips")
    st.caption(
        f"Detection: {manifest.get('moment_mode', 'transcript')} · "
        f"Transcript language: {manifest['transcript'].get('language') or 'not detected'} · "
        f"Ranking: {manifest['scorer']}"
    )
    if manifest.get("visual_analysis", {}).get("enabled"):
        st.caption(
            f"Visual scan: {manifest['visual_analysis']['samples_analysed']} frames sampled · "
            "motion + shot-change signals (not semantic event recognition)"
        )
    for index, item in enumerate(manifest["clips"], start=1):
        left, right = st.columns([1.15, 1])
        with left:
            st.video(item["path"])
        with right:
            suggestion = item["suggested_metadata"]
            st.markdown(f"**{index}. {suggestion['title']}**")
            st.write(" ".join(suggestion["hashtags"]))
            st.caption(
                f"{item['start']:.1f}s–{item['end']:.1f}s · "
                f"Score {item['score']}/100 · {item['reason']}"
            )
            clip_path = Path(item["path"])
            st.download_button(
                "Download MP4",
                data=clip_path.read_bytes(),
                file_name=clip_path.name,
                mime="video/mp4",
                key=f"download-clip-{index}",
            )
        st.divider()

    metadata_path = Path(manifest["metadata_path"])
    manifest_path = Path(manifest["manifest_path"])
    st.download_button(
        "Download titles and hashtags (JSON)",
        data=metadata_path.read_bytes(),
        file_name="metadata.json",
        mime="application/json",
    )
    st.download_button(
        "Download processing manifest (JSON)",
        data=manifest_path.read_bytes(),
        file_name="manifest.json",
        mime="application/json",
    )
    st.info(
        "Review every clip and metadata suggestion before publishing. ClipRally does not "
        "automatically repost downloaded videos. Use the official publishing commands only "
        "for media you have rights to publish."
    )
else:
    st.markdown(
        """**No cloud account is needed for local clipping.** Hybrid mode combines local Whisper """
        """transcription with OpenCV motion and shot-change analysis. Visual-only mode can find """
        """action-heavy windows even when a video has no speech. It does not yet recognise """
        """specific objects or game events. Ollama is optional for local LLM ranking; OpenAI """
        """and Gemini are optional hosted services."""
    )