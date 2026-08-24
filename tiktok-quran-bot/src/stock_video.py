"""Nature clip sourcing.

Searches Pexels (primary) then Pixabay (fallback) for a vertical/portrait clip,
picks the best portrait video file, and downloads it. Provider order comes from
config ``stock.providers``.

Both providers are free but require attribution; the returned StockClip carries
the credit info, which the caller logs so the user can attribute the source.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"
PIXABAY_SEARCH_URL = "https://pixabay.com/api/videos/"
REQUEST_TIMEOUT = 30


@dataclass
class StockClip:
    provider: str
    source_id: str
    path: Path
    width: int
    height: int
    duration: float
    credit: str
    source_url: str


class StockVideoError(RuntimeError):
    """Raised when no provider can supply a usable clip."""


def _is_portrait(width: int, height: int) -> bool:
    return height > width > 0


def pick_pexels_file(video: Dict[str, Any], min_width: int) -> Optional[Dict[str, Any]]:
    """From one Pexels video, choose the best portrait file.

    Preference: portrait files with width >= min_width, smallest such width
    (closest to target, less to downscale); otherwise the largest portrait file.
    """
    files = [f for f in video.get("video_files", []) if _is_portrait(f.get("width", 0), f.get("height", 0))]
    if not files:
        return None
    at_least = [f for f in files if f.get("width", 0) >= min_width]
    if at_least:
        return min(at_least, key=lambda f: f.get("width", 0))
    return max(files, key=lambda f: f.get("width", 0))


def choose_pexels_video(
    videos: List[Dict[str, Any]],
    min_duration: float,
    min_width: int,
    rng: random.Random,
) -> Optional[Dict[str, Any]]:
    """Pick a Pexels video (with a usable portrait file), preferring ones long
    enough to cover the audio; falls back to the longest available."""
    usable = [(v, pick_pexels_file(v, min_width)) for v in videos]
    usable = [(v, f) for v, f in usable if f is not None]
    if not usable:
        return None

    long_enough = [(v, f) for v, f in usable if v.get("duration", 0) >= min_duration]
    pool = long_enough or usable
    video, file = rng.choice(pool)
    return {"video": video, "file": file}


def pick_pixabay_video(hit: Dict[str, Any], min_width: int) -> Optional[Dict[str, Any]]:
    """From one Pixabay hit, choose the best portrait variant."""
    variants = hit.get("videos", {})
    portrait = [
        v for v in variants.values()
        if _is_portrait(v.get("width", 0), v.get("height", 0)) and v.get("url")
    ]
    if not portrait:
        return None
    at_least = [v for v in portrait if v.get("width", 0) >= min_width]
    if at_least:
        return min(at_least, key=lambda v: v.get("width", 0))
    return max(portrait, key=lambda v: v.get("width", 0))


def choose_pixabay_hit(
    hits: List[Dict[str, Any]],
    min_duration: float,
    min_width: int,
    rng: random.Random,
) -> Optional[Dict[str, Any]]:
    usable = [(h, pick_pixabay_video(h, min_width)) for h in hits]
    usable = [(h, v) for h, v in usable if v is not None]
    if not usable:
        return None
    long_enough = [(h, v) for h, v in usable if h.get("duration", 0) >= min_duration]
    pool = long_enough or usable
    hit, variant = rng.choice(pool)
    return {"hit": hit, "variant": variant}


def _download(url: str, dest: Path, headers: Optional[Dict[str, str]] = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, headers=headers, stream=True, timeout=REQUEST_TIMEOUT) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                if chunk:
                    fh.write(chunk)


def _fetch_pexels(config, api_key, query, min_duration, dest, rng) -> Optional[StockClip]:
    stock = config["stock"]
    params = {
        "query": query,
        "orientation": "portrait",
        "per_page": stock.get("results_per_query", 20),
        "size": "medium",
    }
    resp = requests.get(
        PEXELS_SEARCH_URL,
        headers={"Authorization": api_key},
        params=params,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    videos = resp.json().get("videos", [])
    choice = choose_pexels_video(videos, min_duration, stock.get("min_width", 1080), rng)
    if not choice:
        return None

    video, file = choice["video"], choice["file"]
    _download(file["link"], dest)
    return StockClip(
        provider="pexels",
        source_id=str(video.get("id", "")),
        path=dest,
        width=file.get("width", 0),
        height=file.get("height", 0),
        duration=float(video.get("duration", 0) or 0),
        credit=str(video.get("user", {}).get("name", "Unknown")),
        source_url=str(video.get("url", "")),
    )


def _fetch_pixabay(config, api_key, query, min_duration, dest, rng) -> Optional[StockClip]:
    stock = config["stock"]
    params = {
        "key": api_key,
        "q": query,
        "per_page": stock.get("results_per_query", 20),
    }
    resp = requests.get(PIXABAY_SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    hits = resp.json().get("hits", [])
    choice = choose_pixabay_hit(hits, min_duration, stock.get("min_width", 1080), rng)
    if not choice:
        return None

    hit, variant = choice["hit"], choice["variant"]
    _download(variant["url"], dest)
    return StockClip(
        provider="pixabay",
        source_id=str(hit.get("id", "")),
        path=dest,
        width=variant.get("width", 0),
        height=variant.get("height", 0),
        duration=float(hit.get("duration", 0) or 0),
        credit=str(hit.get("user", "Unknown")),
        source_url=str(hit.get("pageURL", "")),
    )


_FETCHERS = {"pexels": _fetch_pexels, "pixabay": _fetch_pixabay}


def _api_key_for(provider: str, secrets) -> str:
    return {
        "pexels": secrets.pexels_api_key,
        "pixabay": secrets.pixabay_api_key,
    }.get(provider, "")


def fetch_clip(config, secrets, min_duration: float, dest: Path, rng: Optional[random.Random] = None) -> StockClip:
    """Try each configured provider in order until one returns a usable clip."""
    rng = rng or random.Random()
    query = rng.choice(config["stock"]["query_terms"])
    logger.info("Searching stock video for query: %r", query)

    errors: List[str] = []
    for provider in config["stock"]["providers"]:
        fetcher = _FETCHERS.get(provider)
        if fetcher is None:
            logger.warning("Unknown stock provider %r; skipping", provider)
            continue
        api_key = _api_key_for(provider, secrets)
        if not api_key:
            logger.info("No API key for %s; skipping", provider)
            errors.append(f"{provider}: no API key")
            continue
        try:
            clip = fetcher(config, api_key, query, min_duration, dest, rng)
            if clip is None:
                logger.info("%s returned no usable portrait clip for %r", provider, query)
                errors.append(f"{provider}: no usable portrait clip")
                continue
            logger.info(
                "Fetched clip from %s (id=%s, %dx%d, %.1fs, credit: %s)",
                clip.provider, clip.source_id, clip.width, clip.height, clip.duration, clip.credit,
            )
            return clip
        except requests.RequestException as exc:
            logger.warning("%s request failed: %s", provider, exc)
            errors.append(f"{provider}: {exc}")
            continue

    raise StockVideoError("Could not fetch a stock clip. Details: " + "; ".join(errors))
