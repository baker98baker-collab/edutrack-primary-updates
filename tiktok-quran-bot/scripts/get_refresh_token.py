#!/usr/bin/env python3
"""One-time helper to obtain a TikTok refresh token via the OAuth (PKCE) flow.

Run this once on a machine with a browser. It opens TikTok's consent screen,
catches the redirect on a small local server, exchanges the code for tokens, and
prints the refresh token to paste into your `.env` as TIKTOK_REFRESH_TOKEN.

Prerequisites (in .env):
  TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REDIRECT_URI
The redirect URI must be registered EXACTLY in your TikTok app settings, and the
app must have the `video.upload` scope enabled.

Usage:
  python scripts/get_refresh_token.py            # scope video.upload
  python scripts/get_refresh_token.py --scope video.upload,video.publish
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import secrets as pysecrets
import sys
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import SECRETS  # noqa: E402

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"

_auth_code = {"code": None, "state": None, "error": None}


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - required name
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        _auth_code["code"] = (params.get("code") or [None])[0]
        _auth_code["state"] = (params.get("state") or [None])[0]
        _auth_code["error"] = (params.get("error") or [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = "Authorization received. You can close this tab and return to the terminal."
        if _auth_code["error"]:
            msg = f"Authorization error: {_auth_code['error']}"
        self.wfile.write(f"<html><body><h3>{msg}</h3></body></html>".encode("utf-8"))

    def log_message(self, *_args):  # silence default logging
        return


def _make_pkce():
    verifier = pysecrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def main() -> int:
    parser = argparse.ArgumentParser(description="Obtain a TikTok refresh token")
    parser.add_argument("--scope", default="video.upload", help="Comma-separated scopes")
    args = parser.parse_args()

    client_key = SECRETS.tiktok_client_key
    client_secret = SECRETS.tiktok_client_secret
    redirect_uri = SECRETS.tiktok_redirect_uri
    if not (client_key and client_secret and redirect_uri):
        print("ERROR: set TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET and "
              "TIKTOK_REDIRECT_URI in .env first.", file=sys.stderr)
        return 1

    parsed = urllib.parse.urlparse(redirect_uri)
    host = parsed.hostname or "localhost"
    port = parsed.port or 8723

    verifier, challenge = _make_pkce()
    state = pysecrets.token_urlsafe(16)
    auth_params = {
        "client_key": client_key,
        "scope": args.scope,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = AUTHORIZE_URL + "?" + urllib.parse.urlencode(auth_params)

    print("\nOpen this URL in your browser to authorize (also attempting to open it):\n")
    print(auth_url + "\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    print(f"Waiting for the redirect on {host}:{port} ...")
    server = HTTPServer((host, port), _CallbackHandler)
    server.handle_request()  # serve exactly one request (the callback)

    if _auth_code["error"]:
        print(f"Authorization failed: {_auth_code['error']}", file=sys.stderr)
        return 1
    if not _auth_code["code"]:
        print("No authorization code received.", file=sys.stderr)
        return 1
    if _auth_code["state"] != state:
        print("State mismatch — aborting for safety.", file=sys.stderr)
        return 1

    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": _auth_code["code"],
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
        timeout=60,
    )
    payload = resp.json()
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        print(f"Token exchange failed: {payload}", file=sys.stderr)
        return 1

    print("\n=== SUCCESS ===")
    print(f"open_id:       {payload.get('open_id')}")
    print(f"scope:         {payload.get('scope')}")
    print(f"expires_in:    {payload.get('expires_in')} (access token)")
    print("\nAdd this line to your .env:\n")
    print(f"TIKTOK_REFRESH_TOKEN={refresh_token}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
