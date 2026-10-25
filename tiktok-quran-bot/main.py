#!/usr/bin/env python3
"""Daily TikTok Qur'an nature-video bot — pipeline orchestrator.

Steps: pick a verified recitation -> fetch a portrait nature clip -> render
Arabic subtitles (.ass) -> compose the vertical MP4 with ffmpeg -> upload to the
TikTok inbox as a draft (unless --no-publish).

Usage:
    python main.py                 # full run (produce + upload draft)
    python main.py --no-publish    # produce the MP4 only, skip TikTok
    python main.py --dry-run       # like --no-publish, plus keep temp files
    python main.py --config path/to/config.json

AMANAH: Qur'anic text/audio are read from your verified files only; nothing is
generated. Entries missing audio or verified text are skipped.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import random
import shutil
import sys
from pathlib import Path

from src import compose, recitation, stock_video, subtitles, tiktok
from src.config import SECRETS, load_config
from src.media import tools_available


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily TikTok Qur'an nature-video bot")
    parser.add_argument("--config", default=None, help="Path to config.json (default: ./config.json)")
    parser.add_argument("--no-publish", action="store_true", help="Produce the MP4 but do not upload to TikTok")
    parser.add_argument("--dry-run", action="store_true", help="Like --no-publish and keep temp files")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    log = logging.getLogger("main")
    config = load_config(args.config)

    if not tools_available():
        log.error("ffmpeg/ffprobe not found on PATH. Install ffmpeg (with libass) and retry.")
        return 2

    tmp_dir = Path(config["paths"]["tmp_dir"])
    output_dir = Path(config["paths"]["output_dir"])
    tmp_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random()

    # 1) Pick a verified recitation (drives the clip duration).
    rec = recitation.select_recitation(config)
    duration = float(rec.duration)

    # 2) Fetch a portrait nature clip long enough (else it is looped in compose).
    nature_path = tmp_dir / "nature_source.mp4"
    clip = stock_video.fetch_clip(config, SECRETS, min_duration=duration, dest=nature_path, rng=rng)

    # 3) Render Arabic subtitles to an .ass file.
    ass_path = tmp_dir / "subtitles.ass"
    subtitles.write_ass(
        ass_path,
        text_ar=rec.text_ar,
        duration=duration,
        style=config["subtitles"],
        width=int(config["video"]["width"]),
        height=int(config["video"]["height"]),
        segments=rec.segments,
    )

    # 4) Compose the final vertical MP4.
    stamp = dt.datetime.now().strftime("%Y%m%d")
    output_path = output_dir / f"{stamp}_{rec.id}.mp4"
    compose.compose_video(config, clip.path, rec.file, ass_path, output_path, duration)
    log.info("Produced %s (source credit: %s / %s)", output_path, clip.provider, clip.credit)

    # 5) Publish to TikTok inbox (draft), unless skipped.
    if args.no_publish or args.dry_run:
        log.info("Skipping upload (%s). Final video: %s",
                 "--dry-run" if args.dry_run else "--no-publish", output_path)
    else:
        result = tiktok.publish(config, SECRETS, output_path)
        log.info("TikTok %s result: publish_id=%s status=%s",
                 result.mode, result.publish_id, result.status)
        if result.status == "FAILED":
            log.error("Publish FAILED: %s", result.detail)
            return 3
        if result.mode == "inbox":
            log.info("Draft sent to your TikTok inbox — open the app to review and post.")

    # 6) Clean up temp files unless dry-run wants them kept.
    if not args.dry_run:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return run(args)
    except Exception as exc:  # noqa: BLE001 - top-level guard for cron logging
        logging.getLogger("main").exception("Run failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
