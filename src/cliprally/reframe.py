"""Optional sampled face-centering for vertical crops."""

from __future__ import annotations

import math
from pathlib import Path


def detect_face_centers(
    media_path: str | Path,
    *,
    start: float,
    duration: float,
    sample_interval: float = 0.5,
) -> list[tuple[float, float]]:
    """Return [(clip-relative seconds, source-frame x center), ...].

    Uses an OpenCV Haar cascade as a lightweight face-centering heuristic. It is not
    active-speaker diarization and is not expected to work for every scene or game.
    """
    if not math.isfinite(start) or not math.isfinite(duration) or start < 0 or duration <= 0:
        raise ValueError("start must be non-negative and duration must be positive and finite")
    if not math.isfinite(sample_interval) or sample_interval <= 0:
        raise ValueError("sample_interval must be positive and finite")
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "Face-centred reframing is optional. Install it with: "
            "pip install 'cliprally[face-tracking]'"
        ) from exc

    capture = cv2.VideoCapture(str(Path(media_path).expanduser().resolve()))
    if not capture.isOpened():
        raise RuntimeError("OpenCV could not open the source video for face tracking")

    cascade_path = str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
    detector = cv2.CascadeClassifier(cascade_path)
    if detector.empty():
        capture.release()
        raise RuntimeError("OpenCV face-detection cascade could not be loaded")

    results: list[tuple[float, float]] = []
    try:
        time_offset = 0.0
        while time_offset <= duration:
            capture.set(cv2.CAP_PROP_POS_MSEC, (start + time_offset) * 1000)
            ok, frame = capture.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = detector.detectMultiScale(
                gray, scaleFactor=1.12, minNeighbors=5, minSize=(36, 36)
            )
            if len(faces):
                # Largest visible face is used as a practical, explainable proxy.
                x, _y, width, _height = max(faces, key=lambda face: int(face[2]) * int(face[3]))
                results.append((time_offset, float(x + width / 2)))
            time_offset += max(0.15, sample_interval)
    finally:
        capture.release()
    return results


def crop_x_expression(
    frame_width: int,
    crop_width: float,
    face_points: list[tuple[float, float]],
) -> str:
    """Build a clamped FFmpeg expression interpolating detected face centers."""
    if not face_points:
        return "(in_w-out_w)/2"
    points = sorted(
        (time_value, center)
        for time_value, center in face_points
        if math.isfinite(time_value) and math.isfinite(center)
    )
    if not points:
        return "(in_w-out_w)/2"
    x_values = [
        max(0.0, min(frame_width - crop_width, center - crop_width / 2))
        for _, center in points
    ]
    if len(points) == 1:
        return f"{x_values[0]:.2f}"

    expression = f"{x_values[-1]:.2f}"
    for index in range(len(points) - 2, -1, -1):
        t0, t1 = points[index][0], points[index + 1][0]
        x0, x1 = x_values[index], x_values[index + 1]
        if t1 <= t0:
            segment = f"{x1:.2f}"
        else:
            segment = f"({x0:.2f}+({x1 - x0:.2f})*(t-{t0:.3f})/{t1 - t0:.3f})"
        expression = f"if(lt(t,{t1:.3f}),{segment},{expression})"
    expression = f"if(lt(t,{points[0][0]:.3f}),{x_values[0]:.2f},{expression})"
    return f"max(0,min(in_w-out_w,{expression}))"