"""Arabic subtitle (.ass) generation for libass.

We emit an Advanced SubStation Alpha file and let ffmpeg's ``subtitles`` filter
render it through libass, which shapes and joins Arabic glyphs and applies
bidi/RTL correctly (HarfBuzz + FriBidi). ffmpeg's ``drawtext`` does neither, so
it is deliberately not used here.

`build_ass` is a pure function (text in, .ass string out) and is unit-tested.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


def _ass_color(hex_rgb: str, alpha: int = 0) -> str:
    """Convert an "RRGGBB" hex string to an ASS "&HAABBGGRR" colour."""
    h = hex_rgb.strip().lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    rr, gg, bb = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{bb}{gg}{rr}".upper()


def _ass_time(seconds: float) -> str:
    """Format seconds as ASS time H:MM:SS.cc (centiseconds)."""
    if seconds < 0:
        seconds = 0.0
    total_cs = int(round(seconds * 100))
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape_text(text: str) -> str:
    """Make text safe for a Dialogue line: collapse real newlines to \\N and
    neutralise brace characters that libass would treat as override tags."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\n", r"\N")
    # Braces start/stop override blocks in ASS; Qur'anic text should not contain
    # them, but guard anyway so stray braces render literally.
    text = text.replace("{", "(").replace("}", ")")
    return text.strip()


def build_ass(
    text_ar: str,
    duration: float,
    style: Dict[str, Any],
    width: int,
    height: int,
    segments: Optional[Sequence[Dict[str, Any]]] = None,
) -> str:
    """Build a complete .ass document.

    If ``segments`` (each {start, end, text_ar}) is provided, one timed line per
    segment is emitted; otherwise the full ``text_ar`` spans the whole clip.
    """
    primary = _ass_color(style.get("primary_color_hex", "FFFFFF"))
    outline_color = _ass_color(style.get("outline_color_hex", "000000"))
    font_name = style.get("font_name", "Amiri")
    font_size = int(style.get("font_size", 64))
    outline = style.get("outline", 3)
    shadow = style.get("shadow", 1)
    alignment = int(style.get("alignment", 2))
    margin_v = int(style.get("margin_v", 220))
    margin_h = int(style.get("margin_h", 80))

    style_line = (
        "Style: Default,{font},{size},{primary},&H000000FF,{outline_c},&H64000000,"
        "0,0,0,0,100,100,0,0,1,{outline},{shadow},{align},{ml},{mr},{mv},1"
    ).format(
        font=font_name,
        size=font_size,
        primary=primary,
        outline_c=outline_color,
        outline=outline,
        shadow=shadow,
        align=alignment,
        ml=margin_h,
        mr=margin_h,
        mv=margin_v,
    )

    header = "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            "YCbCr Matrix: TV.709",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding",
            style_line,
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )

    events: List[str] = []

    valid_segments = [s for s in (segments or []) if s.get("text_ar")]
    if valid_segments:
        for seg in valid_segments:
            start = min(float(seg["start"]), duration)
            end = min(float(seg["end"]), duration)
            if end <= start:
                continue
            events.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,"
                f"{_escape_text(seg['text_ar'])}"
            )
    else:
        events.append(
            f"Dialogue: 0,{_ass_time(0)},{_ass_time(duration)},Default,,0,0,0,,"
            f"{_escape_text(text_ar)}"
        )

    return header + "\n" + "\n".join(events) + "\n"


def write_ass(
    path,
    text_ar: str,
    duration: float,
    style: Dict[str, Any],
    width: int,
    height: int,
    segments: Optional[Sequence[Dict[str, Any]]] = None,
) -> None:
    """Render build_ass output to ``path`` as UTF-8."""
    content = build_ass(text_ar, duration, style, width, height, segments)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
