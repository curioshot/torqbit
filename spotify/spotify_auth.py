"""Spotify Web API auth (Authorization Code + PKCE, loopback). Personal use only.

Token file: ~/.config/spotify-lyrics/tokens.json (0600).
Client id from env SPOTIFY_CLIENT_ID or config file.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

CONFIG_DIR = os.path.expanduser("~/.config/spotify-lyrics")
TOKEN_FILE = os.path.join(CONFIG_DIR, "tokens.json")
SCOPES = "user-read-currently-playing user-read-playback-state"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"


def client_id() -> str | None:
    cid = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    if cid:
        return cid
    cfg = os.path.join(CONFIG_DIR, "config.json")
    try:
        with open(cfg) as f:
            return json.load(f).get("client_id")
    except (OSError, ValueError):
        return None


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def load_tokens() -> dict | None:
    try:
        with open(TOKEN_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_tokens(tok: dict) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(tok, f)
    os.chmod(TOKEN_FILE, 0o600)


def _post_token(data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def login(port: int = 8888) -> dict:
    cid = client_id()
    if not cid:
        raise SystemExit("Set SPOTIFY_CLIENT_ID env var (Spotify dashboard app).")
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    redirect = f"http://127.0.0.1:{port}/callback"
    params = {
        "response_type": "code",
        "client_id": cid,
        "scope": SCOPES,
        "redirect_uri": redirect,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    code_box: dict = {}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "code" in q:
                code_box["code"] = q["code"][0]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Logged in. You can close this tab.")
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing code.")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", port), H)
    t = threading.Thread(target=srv.handle_request, daemon=True)
    t.start()
    webbrowser.open(f"{AUTH_URL}?{urllib.parse.urlencode(params)}")
    print("Opened browser for Spotify login ...")
    t.join(timeout=180)
    srv.server_close()
    if "code" not in code_box:
        raise SystemExit("Login timed out (no code received).")
    tok = _post_token(
        {
            "grant_type": "authorization_code",
            "code": code_box["code"],
            "redirect_uri": redirect,
            "client_id": cid,
            "code_verifier": verifier,
        }
    )
    save_tokens(tok)
    return tok


def access_token() -> str | None:
    tok = load_tokens()
    if not tok:
        return None
    import time

    # refresh proactively 60s before expiry if we know when it was issued
    if tok.get("expires_at", 0) - 60 < time.time() and tok.get("refresh_token"):
        cid = client_id()
        try:
            new = _post_token(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": tok["refresh_token"],
                    "client_id": cid,
                }
            )
            tok["access_token"] = new["access_token"]
            tok["expires_at"] = time.time() + int(new.get("expires_in", 3600))
            if new.get("refresh_token"):
                tok["refresh_token"] = new["refresh_token"]
            save_tokens(tok)
        except Exception:
            pass
    return tok.get("access_token")


def logout() -> None:
    try:
        os.remove(TOKEN_FILE)
    except OSError:
        pass
