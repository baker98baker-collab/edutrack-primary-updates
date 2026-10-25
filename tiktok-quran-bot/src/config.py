"""Configuration loading: merges config.json over built-in defaults and pulls
secrets from the environment (.env).

Kept side-effect-light: `load_config` reads files and env only. Path fields are
resolved to absolute paths rooted at the project directory so the bot behaves
the same whether launched from cron or by hand.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is a declared dependency
    load_dotenv = None

# Project root = the directory that contains this package's parent (tiktok-quran-bot/).
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG: Dict[str, Any] = {
    "video": {
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "video_bitrate": "6M",
        "audio_bitrate": "192k",
    },
    "duration": {
        "target_seconds": 15,
        "max_seconds": 20,
    },
    "stock": {
        "providers": ["pexels", "pixabay"],
        "query_terms": ["nature", "forest", "ocean waves", "mountains", "clouds sky"],
        "min_width": 1080,
        "results_per_query": 20,
    },
    "recitation": {
        "selection_mode": "random_no_repeat",  # or "sequential"
    },
    "subtitles": {
        "font_name": "Amiri",
        "font_size": 64,
        "primary_color_hex": "FFFFFF",
        "outline_color_hex": "000000",
        "outline": 3,
        "shadow": 1,
        "alignment": 2,   # libass numpad alignment: 2 = bottom-center, 5 = middle-center
        "margin_v": 220,
        "margin_h": 80,
    },
    "tiktok": {
        "publish_mode": "inbox",  # "inbox" (draft) or "direct"
        "poll_timeout_seconds": 120,
        "poll_interval_seconds": 5,
    },
    "paths": {
        "recitations_dir": "assets/recitations",
        "metadata_file": "assets/recitations/metadata.json",
        "fonts_dir": "assets/fonts",
        "output_dir": "output",
        "state_file": "state/used.json",
        "tmp_dir": "tmp",
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge ``override`` into a copy of ``base``."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_paths(config: Dict[str, Any]) -> None:
    """Turn every relative path in config['paths'] into an absolute Path."""
    paths = config["paths"]
    for key, value in list(paths.items()):
        p = Path(value)
        paths[key] = p if p.is_absolute() else (PROJECT_ROOT / p)


class Secrets:
    """Environment-backed secrets. Reads lazily so missing keys only matter for
    the step that needs them."""

    @property
    def pexels_api_key(self) -> str:
        return os.getenv("PEXELS_API_KEY", "").strip()

    @property
    def pixabay_api_key(self) -> str:
        return os.getenv("PIXABAY_API_KEY", "").strip()

    @property
    def tiktok_client_key(self) -> str:
        return os.getenv("TIKTOK_CLIENT_KEY", "").strip()

    @property
    def tiktok_client_secret(self) -> str:
        return os.getenv("TIKTOK_CLIENT_SECRET", "").strip()

    @property
    def tiktok_refresh_token(self) -> str:
        return os.getenv("TIKTOK_REFRESH_TOKEN", "").strip()

    @property
    def tiktok_redirect_uri(self) -> str:
        return os.getenv("TIKTOK_REDIRECT_URI", "http://localhost:8723/callback").strip()


def load_config(config_path: str | os.PathLike | None = None) -> Dict[str, Any]:
    """Load merged configuration.

    Order of precedence (low to high): DEFAULT_CONFIG < config.json.
    Also loads the .env file (if python-dotenv is available) so secrets become
    visible via the Secrets object / os.environ.
    """
    if load_dotenv is not None:
        load_dotenv(PROJECT_ROOT / ".env")

    config = copy.deepcopy(DEFAULT_CONFIG)

    if config_path is None:
        candidate = PROJECT_ROOT / "config.json"
        config_path = candidate if candidate.exists() else None

    if config_path is not None:
        with open(config_path, "r", encoding="utf-8") as fh:
            user_config = json.load(fh)
        config = _deep_merge(config, user_config)

    # Ensure a paths block always exists, then resolve to absolute paths.
    config.setdefault("paths", copy.deepcopy(DEFAULT_CONFIG["paths"]))
    for key, value in DEFAULT_CONFIG["paths"].items():
        config["paths"].setdefault(key, value)
    _resolve_paths(config)

    return config


SECRETS = Secrets()
