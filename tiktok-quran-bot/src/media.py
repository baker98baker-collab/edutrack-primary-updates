"""Small shared helpers around the ffmpeg/ffprobe command-line tools."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class MediaToolError(RuntimeError):
    """Raised when ffmpeg/ffprobe is missing or a media command fails."""


def tool_path(name: str) -> str:
    """Return the resolved path to a required CLI tool, or raise a clear error."""
    path = shutil.which(name)
    if not path:
        raise MediaToolError(
            f"'{name}' was not found on PATH. Install ffmpeg (which provides both "
            f"ffmpeg and ffprobe), built with libass/HarfBuzz/FriBidi for Arabic."
        )
    return path


def tools_available() -> bool:
    """True only if both ffmpeg and ffprobe are present."""
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def probe_duration_seconds(media_path: str | Path) -> float:
    """Return the duration of an audio/video file in seconds via ffprobe."""
    ffprobe = tool_path("ffprobe")
    media_path = str(media_path)
    cmd = [
        ffprobe,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        media_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaToolError(f"ffprobe failed for {media_path}: {proc.stderr.strip()}")

    data = json.loads(proc.stdout or "{}")

    # Prefer the container/format duration; fall back to the longest stream.
    fmt_duration = (data.get("format") or {}).get("duration")
    if fmt_duration is not None:
        try:
            return float(fmt_duration)
        except (TypeError, ValueError):
            pass

    durations = []
    for stream in data.get("streams", []):
        value = stream.get("duration")
        if value is not None:
            try:
                durations.append(float(value))
            except (TypeError, ValueError):
                continue
    if durations:
        return max(durations)

    raise MediaToolError(f"Could not determine duration for {media_path}")
