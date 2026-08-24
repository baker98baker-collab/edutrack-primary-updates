"""Unit tests for the side-effect-free logic: recitation selection, subtitle
generation, stock-file picking, and the ffmpeg command builder.

These run without ffmpeg, network, or API keys. Run with: pytest -q
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import recitation, stock_video, subtitles  # noqa: E402
from src.compose import build_ffmpeg_command, _escape_filtergraph_value  # noqa: E402
from src.config import DEFAULT_CONFIG, load_config  # noqa: E402


# --- recitation.choose --------------------------------------------------------

def test_choose_sequential_advances_and_wraps():
    ids = ["a", "b", "c"]
    chosen, used = recitation.choose(ids, [], "sequential")
    assert chosen == "a"
    chosen, used = recitation.choose(ids, ["a"], "sequential")
    assert chosen == "b"
    chosen, used = recitation.choose(ids, ["c"], "sequential")
    assert chosen == "a"  # wraps around


def test_choose_random_no_repeat_cycles_through_all():
    ids = ["a", "b", "c"]
    rng = random.Random(1234)
    seen = []
    used = []
    for _ in range(3):
        chosen, used = recitation.choose(ids, used, "random_no_repeat", rng=rng)
        seen.append(chosen)
    assert sorted(seen) == ["a", "b", "c"]  # no repeats within a cycle


def test_choose_random_no_repeat_resets_after_cycle():
    ids = ["a", "b"]
    rng = random.Random(7)
    chosen, used = recitation.choose(ids, ["a", "b"], "random_no_repeat", rng=rng)
    assert chosen in ids
    assert used == [chosen]  # cycle reset, only the new pick is retained


def test_choose_raises_on_empty():
    try:
        recitation.choose([], [], "sequential")
    except recitation.NoEligibleRecitationError:
        return
    raise AssertionError("expected NoEligibleRecitationError")


def test_filter_eligible_respects_cap():
    recs = [
        recitation.Recitation(id="short", file=Path("s.mp3"), text_ar="x", duration=10.0),
        recitation.Recitation(id="long", file=Path("l.mp3"), text_ar="y", duration=25.0),
        recitation.Recitation(id="unprobed", file=Path("u.mp3"), text_ar="z", duration=None),
    ]
    eligible = recitation.filter_eligible(recs, max_seconds=20.0)
    assert [r.id for r in eligible] == ["short"]


# --- subtitles.build_ass ------------------------------------------------------

def test_build_ass_single_line_spans_duration():
    ass = subtitles.build_ass("نص الآية", 15.0, DEFAULT_CONFIG["subtitles"], 1080, 1920)
    assert "[Script Info]" in ass
    assert "PlayResX: 1080" in ass and "PlayResY: 1920" in ass
    assert "نص الآية" in ass
    assert "0:00:00.00,0:00:15.00" in ass
    assert ass.count("Dialogue:") == 1


def test_build_ass_uses_segments_when_present():
    segs = [
        {"start": 0.0, "end": 5.0, "text_ar": "الأول"},
        {"start": 5.0, "end": 9.0, "text_ar": "الثاني"},
    ]
    ass = subtitles.build_ass("full", 15.0, DEFAULT_CONFIG["subtitles"], 1080, 1920, segments=segs)
    assert ass.count("Dialogue:") == 2
    assert "الأول" in ass and "الثاني" in ass


def test_build_ass_clamps_segment_to_duration():
    segs = [{"start": 0.0, "end": 30.0, "text_ar": "طويل"}]
    ass = subtitles.build_ass("x", 12.0, DEFAULT_CONFIG["subtitles"], 1080, 1920, segments=segs)
    assert "0:00:12.00" in ass  # end clamped to clip duration


def test_ass_color_conversion():
    # White RRGGBB -> ASS &HAABBGGRR opaque
    assert subtitles._ass_color("FFFFFF") == "&H00FFFFFF"
    # Pure red -> blue/green 00, red FF
    assert subtitles._ass_color("FF0000") == "&H000000FF"


def test_escape_text_handles_newlines_and_braces():
    out = subtitles._escape_text("line1\nline2{tag}")
    assert r"\N" in out
    assert "{" not in out and "}" not in out


# --- stock_video picking ------------------------------------------------------

def test_pick_pexels_file_prefers_portrait_at_min_width():
    video = {
        "video_files": [
            {"width": 720, "height": 1280, "link": "a"},
            {"width": 1080, "height": 1920, "link": "b"},
            {"width": 2160, "height": 3840, "link": "c"},
            {"width": 1920, "height": 1080, "link": "landscape"},
        ]
    }
    chosen = stock_video.pick_pexels_file(video, min_width=1080)
    assert chosen["link"] == "b"  # smallest portrait >= 1080


def test_pick_pexels_file_none_when_no_portrait():
    video = {"video_files": [{"width": 1920, "height": 1080, "link": "x"}]}
    assert stock_video.pick_pexels_file(video, 1080) is None


def test_pick_pixabay_video_selects_portrait():
    hit = {
        "videos": {
            "large": {"width": 1920, "height": 1080, "url": "land"},
            "medium": {"width": 1080, "height": 1920, "url": "port"},
        }
    }
    chosen = stock_video.pick_pixabay_video(hit, 1080)
    assert chosen["url"] == "port"


# --- compose command builder --------------------------------------------------

def test_escape_filtergraph_value():
    assert _escape_filtergraph_value("/a/b c.ass") == "/a/b c.ass"
    assert _escape_filtergraph_value("/a:b") == "/a\\:b"


def test_build_ffmpeg_command_shape(tmp_path):
    config = load_config(config_path=None)
    cmd = build_ffmpeg_command(
        config,
        nature_path=tmp_path / "n.mp4",
        audio_path=tmp_path / "a.mp3",
        ass_path=tmp_path / "s.ass",
        output_path=tmp_path / "out.mp4",
        duration=15.0,
    )
    assert cmd[0].endswith("ffmpeg")
    assert "-stream_loop" in cmd and "-1" in cmd
    joined = " ".join(cmd)
    assert "scale=1080:1920:force_original_aspect_ratio=increase" in joined
    assert "crop=1080:1920" in joined
    assert "subtitles=filename=" in joined
    assert "-map" in cmd and "[v]" in cmd and "1:a" in cmd
    assert cmd[-1].endswith("out.mp4")
    # duration passed via -t
    ti = cmd.index("-t")
    assert cmd[ti + 1].startswith("15")
