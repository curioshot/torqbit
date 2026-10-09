"""Detect the currently-playing Spotify track.

Providers (unified TrackSnapshot):
  web        Spotify Web API (app + open.spotify.com + phone/speakers, needs login)
  mpris      Linux D-Bus MPRIS (desktop app offline; also browser web player)
  smtc       Windows SystemMediaTransportControls (needs Windows)
  applescript  macOS Spotify.app via osascript (needs macOS)
  auto       web if logged in, else OS-native for this platform
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass


@dataclass
class TrackSnapshot:
    provider: str
    title: str
    artist: str
    album: str
    duration_ms: int
    progress_ms: int
    is_playing: bool
    track_key: str  # stable id for change detection (spotify id or title|artist|dur)
    source: str = ""  # e.g. bus name / device name

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------- MPRIS (Linux)
_MPRIS_BASE = "org.mpris.MediaPlayer2"
_MPRIS_PATH = "/org/mpris/MediaPlayer2"
_MPRIS_PLAYER = "org.mpris.MediaPlayer2.Player"


def _busctl_json(*args: str, timeout: int = 5):
    try:
        out = subprocess.run(
            ["busctl", "--user", "--json=short", *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)
    except ValueError:
        return None


def _mpris_names() -> list[str]:
    """All MPRIS player bus names on the session bus."""
    try:
        out = subprocess.run(
            ["busctl", "--user", "list", "--no-legend", "--no-pager"],
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    names = []
    for line in out.stdout.splitlines():
        parts = line.split()
        if parts and parts[0].startswith(_MPRIS_BASE + "."):
            names.append(parts[0])
    return names


def _unwrap(node) -> object:
    """busctl --json node -> plain python (variant {type,data} unwrapped)."""
    if isinstance(node, dict) and set(node.keys()) == {"type", "data"}:
        t, d = node["type"], node["data"]
        if t == "a{sv}":
            return {k: _unwrap(v) for k, v in d.items()}
        if t.startswith("a"):
            return [_unwrap(v) for v in d]
        return d
    if isinstance(node, dict):
        return {k: _unwrap(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_unwrap(v) for v in node]
    return node


def _mpris_get(bus: str, prop: str):
    node = _busctl_json("get-property", bus, _MPRIS_PATH, _MPRIS_PLAYER, prop)
    if node is None:
        return None
    return _unwrap(node)


def _snapshot_from_mpris(bus: str) -> TrackSnapshot | None:
    status = _mpris_get(bus, "PlaybackStatus")
    if status is None:
        return None
    md = _mpris_get(bus, "Metadata") or {}
    if not isinstance(md, dict):
        return None
    title = str(md.get("xesam:title", "") or "")
    artists = md.get("xesam:artist") or []
    artist = ", ".join(artists) if isinstance(artists, list) else str(artists)
    album = str(md.get("xesam:album", "") or "")
    length_us = md.get("mpris:length", 0) or 0
    try:
        duration_ms = int(int(length_us) // 1000)
    except (ValueError, TypeError):
        duration_ms = 0
    if not title:
        return None
    pos_us = _mpris_get(bus, "Position") or 0
    try:
        progress_ms = int(int(pos_us) // 1000)
    except (ValueError, TypeError):
        progress_ms = 0
    url = str(md.get("xesam:url", "") or "")
    trackid = str(md.get("mpris:trackid", "") or "")
    if "/track/" in url:
        sid = url.rstrip("/").split("/")[-1].split("?")[0]
        key = f"spotify:{sid}"
    elif trackid:
        key = f"mpris:{trackid}"
    else:
        key = f"local:{title}|{artist}|{duration_ms}"
    return TrackSnapshot(
        provider="mpris",
        title=title, artist=artist, album=album,
        duration_ms=duration_ms,
        progress_ms=max(0, min(progress_ms, duration_ms or progress_ms)),
        is_playing=(status == "Playing"),
        track_key=key,
        source=bus,
    )


def get_mpris(prefer_spotify: bool = True) -> TrackSnapshot | None:
    names = _mpris_names()
    if not names:
        return None
    ordered = sorted(
        names, key=lambda n: (0 if n == _MPRIS_BASE + ".spotify" else 1, n)
    ) if prefer_spotify else names
    for bus in ordered:
        try:
            snap = _snapshot_from_mpris(bus)
        except Exception:
            continue
        if snap:
            return snap
    return None


# ------------------------------------------------------- Web API (all OSes)
def get_web() -> TrackSnapshot | None:
    from spotify_auth import access_token

    tok = access_token()
    if not tok:
        return None
    for path in ("/v1/me/player/currently-playing", "/v1/me/player"):
        try:
            req = urllib.request.Request(
                f"https://api.spotify.com{path}?additional_types=track,episode",
                headers={"Authorization": f"Bearer {tok}"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status == 204:
                    return None
                data = json.load(r)
        except Exception:
            continue
        if not data or not data.get("item"):
            continue
        if data.get("currently_playing_type") not in (None, "track"):
            return None  # ad / podcast / unknown: no lyrics timing
        item = data["item"]
        artists = ", ".join(a.get("name", "") for a in item.get("artists", []))
        sid = item.get("id", "")
        return TrackSnapshot(
            provider="web",
            title=item.get("name", ""),
            artist=artists,
            album=(item.get("album") or {}).get("name", ""),
            duration_ms=int(item.get("duration_ms", 0)),
            progress_ms=int(data.get("progress_ms", 0)),
            is_playing=bool(data.get("is_playing", False)),
            track_key=f"spotify:{sid}" if sid else f"web:{item.get('name')}|{artists}",
            source=str((data.get("device") or {}).get("name", "")),
        )
    return None


# ------------------------------------------------------- Windows SMTC
_SMTС_PS = r"""
$mgr = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager,Windows.Media.Control,ContentType=WindowsRuntime]::RequestAsync().GetAwaiter().GetResult()
$s = $mgr.GetCurrentSession()
if ($null -eq $s) { Write-Output '{}'; exit }
$p = $s.TryGetMediaPropertiesAsync().GetAwaiter().GetResult()
$i = $s.GetPlaybackInfo(); $t = $s.GetTimelineProperties()
$o = @{ title=$p.Title; artist=$p.Artist; album=$p.AlbumTitle;
  status=$i.PlaybackStatus.ToString(); posMs=[long]$t.Position.TotalMilliseconds;
  endMs=[long]$t.EndTime.TotalMilliseconds; src=$s.SourceAppUserModelId } | ConvertTo-Json -Compress
Write-Output $o
"""


def get_smtc() -> TrackSnapshot | None:
    if platform.system() != "Windows":
        return None
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", _SMTС_PS],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    try:
        d = json.loads(out.stdout.strip() or "{}")
    except ValueError:
        return None
    if not d.get("title"):
        return None
    playing = str(d.get("status", "")).lower() == "playing"
    dur = int(d.get("endMs") or 0)
    pos = int(d.get("posMs") or 0)
    title, artist = d.get("title", ""), d.get("artist", "")
    return TrackSnapshot(
        provider="smtc", title=title, artist=artist,
        album=d.get("album", ""), duration_ms=dur,
        progress_ms=max(0, min(pos, dur or pos)),
        is_playing=playing,
        track_key=f"local:{title}|{artist}|{dur}",
        source=d.get("src", ""),
    )


# ------------------------------------------------------- macOS AppleScript
_APPLESCRIPT = (
    'tell application "System Events" to set r to '
    '(exists process "Spotify")\n'
    'if r then tell application "Spotify" to return '
    '(name of current track) & "‖" & (artist of current track) & "‖" & '
    '(album of current track) & "‖" & (duration of current track) & "‖" & '
    '(player position) & "‖" & (player state as text)\n'
)


def get_applescript() -> TrackSnapshot | None:
    if platform.system() != "Darwin":
        return None
    try:
        out = subprocess.run(
            ["osascript", "-e", _APPLESCRIPT],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0 or "‖" not in out.stdout:
        return None
    parts = out.stdout.strip().split("‖")
    if len(parts) != 6:
        return None
    title, artist, album, dur, pos, state = parts
    try:
        duration_ms = int(float(dur))
        progress_ms = int(float(pos) * 1000)
    except ValueError:
        return None
    return TrackSnapshot(
        provider="applescript", title=title, artist=artist, album=album,
        duration_ms=duration_ms,
        progress_ms=max(0, min(progress_ms, duration_ms or progress_ms)),
        is_playing=(state.strip().lower() == "playing"),
        track_key=f"local:{title}|{artist}|{duration_ms}",
        source="Spotify.app",
    )


# ---------------------------------------------------------------- dispatcher
def get_snapshot(provider: str = "auto") -> TrackSnapshot | None:
    provider = (provider or "auto").lower()
    if provider == "web":
        return get_web()
    if provider == "mpris":
        return get_mpris()
    if provider == "smtc":
        return get_smtc()
    if provider == "applescript":
        return get_applescript()
    # auto: web (covers app+web+remote) if logged in, else OS-native
    if provider == "auto":
        snap = get_web()
        if snap:
            return snap
        system = platform.system()
        if system == "Linux":
            return get_mpris()
        if system == "Windows":
            return get_smtc()
        if system == "Darwin":
            return get_applescript()
        return get_mpris()
    raise SystemExit(f"Unknown provider: {provider}")


if __name__ == "__main__":
    prov = sys.argv[1] if len(sys.argv) > 1 else "auto"
    snap = get_snapshot(prov)
    print(json.dumps(snap.to_dict() if snap else None, indent=2))
