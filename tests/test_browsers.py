"""browsers.py — the ~/.local/bin wrapper.

install_shim writes a shell script into the user's PATH. Getting this wrong
is the only finding in the codebase that can damage the machine outside
this repo, so the refusal cases are tested directly.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from island import browsers


@pytest.fixture
def shim_dir(tmp_path, monkeypatch):
    d = tmp_path / "bin"
    d.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(browsers, "_shim_dir", lambda: d)
    monkeypatch.setattr(browsers, "_shim_cache", {})
    return d


def _fake_browser(tmp_path: Path, name: str) -> Path:
    real = tmp_path / "real" / name
    real.parent.mkdir(parents=True, exist_ok=True)
    real.write_text("#!/bin/sh\n")
    real.chmod(0o755)
    return real


def test_install_writes_an_executable_wrapper(shim_dir, tmp_path, monkeypatch):
    real = _fake_browser(tmp_path, "chromium")
    browsers._invalidate_shim_cache()
    monkeypatch.setattr(browsers, "find", lambda family: str(real))
    res = browsers.install_shim("chromium")
    assert res["ok"], res
    target = shim_dir / "chromium"
    assert target.exists()
    assert os.access(target, os.X_OK)
    body = target.read_text()
    assert str(real) in body
    assert browsers.SHIM_MARKER in body


def test_install_refuses_to_exec_itself(shim_dir, tmp_path, monkeypatch):
    """If PATH resolves 'chromium' to the very file we are about to write,
    the wrapper's exec line targets itself and every launch forks forever."""
    target = shim_dir / "chromium"
    target.write_text("#!/bin/sh\n# my own launcher\n")
    target.chmod(0o755)
    monkeypatch.setattr(browsers, "find", lambda family: str(target))
    res = browsers.install_shim("chromium")
    assert res["ok"] is False
    assert "itself" in res["error"] or "already exists" in res["error"]
    # The user's file must be untouched.
    assert "my own launcher" in target.read_text()


def test_install_never_clobbers_a_foreign_file(shim_dir, tmp_path, monkeypatch):
    """Ticking the checkbox must not silently destroy a personal launcher
    already sitting at that path."""
    target = shim_dir / "chromium"
    original = "#!/bin/sh\nexec /opt/mine/chromium --profile ~/work\n"
    target.write_text(original)
    target.chmod(0o755)
    real = _fake_browser(tmp_path, "chromium")
    monkeypatch.setattr(browsers, "find", lambda family: str(real))
    res = browsers.install_shim("chromium")
    assert res["ok"] is False
    assert "not a bot-island wrapper" in res["error"]
    assert target.read_text() == original


def test_install_is_idempotent(shim_dir, tmp_path, monkeypatch):
    real = _fake_browser(tmp_path, "chromium")
    monkeypatch.setattr(browsers, "find", lambda family: str(real))
    first = browsers.install_shim("chromium")
    second = browsers.install_shim("chromium")
    assert first["ok"] and not first.get("already")
    assert second["ok"] and second.get("already")


def test_uninstall_reports_honestly_when_there_was_nothing(shim_dir):
    """It used to return ok/already=False, which the UI rendered as
    'Removed the wrapper' — a false success."""
    res = browsers.uninstall_shim("chromium")
    assert res["ok"] is True
    assert res.get("removed") == [], "claimed to remove something it did not"


def test_uninstall_removes_every_wrapper_for_the_family(shim_dir):
    for name in ("chromium", "chromium-browser"):
        p = shim_dir / name
        p.write_text(f"#!/usr/bin/env bash\n# {browsers.SHIM_MARKER} wrapper for chromium\n")
        p.chmod(0o755)
    browsers._invalidate_shim_cache()
    res = browsers.uninstall_shim("chromium")
    assert res["ok"] and len(res["removed"]) == 2


def test_shim_installed_matches_what_is_on_disk(shim_dir, tmp_path):
    """service_tab called browsers.shim_installed(), which did not exist —
    the AttributeError was swallowed and the checkbox always read 'off'."""
    assert hasattr(browsers, "shim_installed")
    assert browsers.shim_installed("chromium") is False
    (shim_dir / "chromium").write_text(
        f"#!/usr/bin/env bash\n# {browsers.SHIM_MARKER} wrapper for chromium\n")
    browsers._invalidate_shim_cache()
    assert browsers.shim_installed("chromium") is True


def test_find_skips_our_own_wrapper(shim_dir, tmp_path):
    """Recursion guard: discovery must never resolve to the wrapper."""
    real = _fake_browser(tmp_path, "chromium")
    marker = (shim_dir / "chromium")
    marker.write_text(f"#!/usr/bin/env bash\n# {browsers.SHIM_MARKER} wrapper for chromium\n")
    marker.chmod(0o755)
    assert browsers._is_shim(str(marker)) is True
    assert browsers._is_shim(str(real)) is False
