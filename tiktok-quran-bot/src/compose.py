"""Video composition via a single ffmpeg invocation.

Takes the nature clip + recitation audio + generated .ass subtitles and produces
a 1080x1920 H.264/AAC MP4 whose length equals the recitation (the nature clip is
looped and trimmed to match, so the ayah is never cut).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from .media import MediaToolError, tool_path

logger = logging.getLogger(__name__)


def _escape_filtergraph_value(value: str) -> str:
    """Escape a path for use as a value inside an ffmpeg filtergraph option.

    Order matters: backslash first, then the characters special to the
    filtergraph parser. Args are passed to ffmpeg as a list (no shell), so only
    filtergraph-level escaping is required.
    """
    value = value.replace("\\", "\\\\")
    value = value.replace(":", "\\:")
    value = value.replace("'", "\\'")
    return value


def build_ffmpeg_command(
    config: Dict[str, Any],
    nature_path: Path,
    audio_path: Path,
    ass_path: Path,
    output_path: Path,
    duration: float,
    ffmpeg_bin: str = "ffmpeg",
) -> List[str]:
    """Assemble the ffmpeg argument list (pure; no execution).

    ``ffmpeg_bin`` defaults to the bare name so this builder needs nothing
    installed; compose_video passes the resolved absolute path.
    """
    video = config["video"]
    width = int(video["width"])
    height = int(video["height"])
    fps = int(video["fps"])
    fonts_dir = Path(config["paths"]["fonts_dir"])

    subtitles_arg = (
        f"subtitles=filename='{_escape_filtergraph_value(str(ass_path))}'"
        f":fontsdir='{_escape_filtergraph_value(str(fonts_dir))}'"
    )
    filtergraph = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},{subtitles_arg},fps={fps},format=yuv420p[v]"
    )

    return [
        ffmpeg_bin,
        "-y",
        "-stream_loop", "-1", "-i", str(nature_path),
        "-i", str(audio_path),
        "-t", f"{duration:.3f}",
        "-filter_complex", filtergraph,
        "-map", "[v]",
        "-map", "1:a",
        "-c:v", "libx264",
        "-profile:v", "high",
        "-preset", "medium",
        "-b:v", str(video.get("video_bitrate", "6M")),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", str(video.get("audio_bitrate", "192k")),
        "-ar", "44100",
        "-movflags", "+faststart",
        str(output_path),
    ]


def compose_video(
    config: Dict[str, Any],
    nature_path: Path,
    audio_path: Path,
    ass_path: Path,
    output_path: Path,
    duration: float,
) -> Path:
    """Run ffmpeg to produce the final MP4. Raises MediaToolError on failure."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = tool_path("ffmpeg")
    cmd = build_ffmpeg_command(
        config, nature_path, audio_path, ass_path, output_path, duration, ffmpeg_bin=ffmpeg_bin
    )
    logger.info("Composing video -> %s (%.1fs)", output_path, duration)
    logger.debug("ffmpeg command: %s", " ".join(cmd))

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        # ffmpeg logs everything to stderr; surface the tail for diagnosis.
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise MediaToolError(f"ffmpeg failed (exit {proc.returncode}):\n{tail}")

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise MediaToolError(f"ffmpeg reported success but {output_path} is missing/empty")

    logger.info("Wrote %s (%.1f KB)", output_path, output_path.stat().st_size / 1024)
    return output_path
