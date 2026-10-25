"""TikTok Content Posting API client.

Default flow is "upload to inbox" (a draft): the video is sent to the account's
TikTok inbox, and the user opens the app to finish and publish it. This needs
only the ``video.upload`` scope and keeps a human in the loop before anything
goes public. A ``direct`` mode (scope ``video.publish``) is also implemented for
audited apps; unaudited apps may only direct-post privately (SELF_ONLY).

API base: https://open.tiktokapis.com
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
INBOX_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
DIRECT_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
CREATOR_INFO_URL = "https://open.tiktokapis.com/v2/post/publish/creator_info/query/"

REQUEST_TIMEOUT = 60
# Terminal statuses returned by status/fetch.
_TERMINAL = {"SEND_TO_USER_INBOX", "PUBLISH_COMPLETE", "FAILED"}


class TikTokError(RuntimeError):
    """Raised on any TikTok API error."""


@dataclass
class PublishResult:
    publish_id: str
    status: str
    mode: str
    detail: Dict[str, Any]


def _check_api_error(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the {data, error} envelope; return data or raise."""
    error = payload.get("error") or {}
    code = error.get("code", "ok")
    if code and code != "ok":
        raise TikTokError(
            f"TikTok API error: code={code} message={error.get('message')!r} "
            f"log_id={error.get('log_id')}"
        )
    return payload.get("data", {}) or {}


def refresh_access_token(client_key: str, client_secret: str, refresh_token: str) -> Dict[str, Any]:
    """Exchange a refresh token for a fresh access token."""
    if not (client_key and client_secret and refresh_token):
        raise TikTokError(
            "Missing TikTok credentials. Set TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET "
            "and TIKTOK_REFRESH_TOKEN in .env (see scripts/get_refresh_token.py)."
        )
    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=REQUEST_TIMEOUT,
    )
    payload = resp.json()
    if "access_token" not in payload:
        raise TikTokError(f"Token refresh failed: {payload}")
    logger.info("Refreshed TikTok access token (scope: %s)", payload.get("scope", "?"))
    return payload


def _auth_headers(access_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }


def _init_inbox(access_token: str, video_size: int) -> Dict[str, Any]:
    body = {
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": video_size,   # single-chunk upload for a short clip
            "total_chunk_count": 1,
        }
    }
    resp = requests.post(INBOX_INIT_URL, headers=_auth_headers(access_token), json=body, timeout=REQUEST_TIMEOUT)
    data = _check_api_error(resp.json())
    if not data.get("upload_url") or not data.get("publish_id"):
        raise TikTokError(f"Inbox init returned no upload_url/publish_id: {data}")
    return data


def _init_direct(access_token: str, video_size: int, config: Dict[str, Any]) -> Dict[str, Any]:
    tiktok_cfg = config.get("tiktok", {})
    body = {
        "post_info": {
            "title": tiktok_cfg.get("default_title", ""),
            # Unaudited apps may only post privately.
            "privacy_level": tiktok_cfg.get("privacy_level", "SELF_ONLY"),
            "disable_comment": tiktok_cfg.get("disable_comment", False),
            "disable_duet": tiktok_cfg.get("disable_duet", False),
            "disable_stitch": tiktok_cfg.get("disable_stitch", False),
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": video_size,
            "total_chunk_count": 1,
        },
    }
    resp = requests.post(DIRECT_INIT_URL, headers=_auth_headers(access_token), json=body, timeout=REQUEST_TIMEOUT)
    data = _check_api_error(resp.json())
    if not data.get("upload_url") or not data.get("publish_id"):
        raise TikTokError(f"Direct init returned no upload_url/publish_id: {data}")
    return data


def _put_file(upload_url: str, video_path: Path, video_size: int) -> None:
    with open(video_path, "rb") as fh:
        data = fh.read()
    headers = {
        "Content-Type": "video/mp4",
        "Content-Length": str(video_size),
        "Content-Range": f"bytes 0-{video_size - 1}/{video_size}",
    }
    resp = requests.put(upload_url, headers=headers, data=data, timeout=REQUEST_TIMEOUT)
    if resp.status_code not in (200, 201, 206):
        raise TikTokError(f"Video upload PUT failed: HTTP {resp.status_code} {resp.text[:300]}")


def poll_status(access_token: str, publish_id: str, timeout: int, interval: int) -> Dict[str, Any]:
    """Poll status/fetch until a terminal status or timeout."""
    deadline = time.monotonic() + timeout
    last: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        resp = requests.post(
            STATUS_URL,
            headers=_auth_headers(access_token),
            json={"publish_id": publish_id},
            timeout=REQUEST_TIMEOUT,
        )
        last = _check_api_error(resp.json())
        status = last.get("status", "")
        logger.info("Publish %s status: %s", publish_id, status or "?")
        if status in _TERMINAL:
            return last
        time.sleep(interval)
    logger.warning("Polling timed out for %s; last status: %s", publish_id, last.get("status"))
    return last


def publish(config: Dict[str, Any], secrets, video_path: Path) -> PublishResult:
    """Refresh token, upload the video per configured mode, and poll to completion."""
    token_payload = refresh_access_token(
        secrets.tiktok_client_key,
        secrets.tiktok_client_secret,
        secrets.tiktok_refresh_token,
    )
    access_token = token_payload["access_token"]

    video_size = video_path.stat().st_size
    if video_size == 0:
        raise TikTokError(f"Refusing to upload empty file: {video_path}")

    mode = config.get("tiktok", {}).get("publish_mode", "inbox")
    if mode == "direct":
        init = _init_direct(access_token, video_size, config)
    else:
        mode = "inbox"
        init = _init_inbox(access_token, video_size)

    publish_id = init["publish_id"]
    logger.info("Initialized %s upload (publish_id=%s)", mode, publish_id)

    _put_file(init["upload_url"], video_path, video_size)
    logger.info("Uploaded %d bytes; polling status...", video_size)

    tiktok_cfg = config.get("tiktok", {})
    detail = poll_status(
        access_token,
        publish_id,
        timeout=int(tiktok_cfg.get("poll_timeout_seconds", 120)),
        interval=int(tiktok_cfg.get("poll_interval_seconds", 5)),
    )
    return PublishResult(
        publish_id=publish_id,
        status=detail.get("status", "UNKNOWN"),
        mode=mode,
        detail=detail,
    )
