"""Optional MCP server exposing local ClipRally clipping to MCP clients."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any


def create_server() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError("Install MCP support with: pip install 'cliprally[mcp]'") from exc

    from .pipeline import process_video

    server = FastMCP("ClipRally")

    @server.tool()
    def clip_local_video(
        video_path: str,
        output_dir: str,
        clips: int = 3,
        scorer: str = "heuristic",
        face_tracking: bool = False,
        rights_confirmed: bool = False,
        moment_mode: str = "transcript",
        min_duration: float = 15.0,
        max_duration: float = 55.0,
        visual_sample_interval: float = 1.5,
    ) -> str:
        """Create local clips using transcript, hybrid, or visual activity detection."""
        if not rights_confirmed:
            return json.dumps(
                {
                    "error": (
                        "Set rights_confirmed=true only after confirming you may edit "
                        "and share clips from this media."
                    )
                }
            )
        source = Path(video_path).expanduser().resolve()
        output = Path(output_dir).expanduser().resolve()
        if not source.is_file():
            return json.dumps({"error": f"Video file does not exist: {source}"})
        manifest = process_video(
            source,
            output,
            clips=clips,
            scorer=scorer,
            face_tracking=face_tracking,
            moment_mode=moment_mode,
            min_duration=min_duration,
            max_duration=max_duration,
            visual_sample_interval=visual_sample_interval,
        )
        return json.dumps(manifest, indent=2)

    @server.tool()
    def inspect_video(video_path: str) -> str:
        """Read duration, dimensions, and codecs for a local video file."""
        from .media import probe_media

        return json.dumps(asdict(probe_media(video_path)))

    return server


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()