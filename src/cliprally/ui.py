"""Launch the optional local Streamlit interface."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    try:
        import streamlit  # noqa: F401
    except ImportError as exc:
        print("Install the local UI with: pip install 'cliprally[ui]'", file=sys.stderr)
        raise SystemExit(2) from exc

    app = Path(__file__).with_name("ui_app.py")
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app)])