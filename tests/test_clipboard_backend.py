"""configure_clipboard() backend selection.

On Wayland, pyperclip defaults to wl-copy; on compositors without a
data-control protocol (GNOME < 47) wl-copy briefly steals keyboard focus
to own the selection, which breaks paste into Electron apps (the inner
input field never regains focus, so the synthesized Ctrl+V lands
nowhere). configure_clipboard() reroutes pyperclip through xclip /
XWayland in that situation. These tests pin the selection logic; the
actual clipboard round-trip is environment-dependent and exercised
manually.
"""
import sys
from unittest import mock

import pytest

import scribe.keyboard as kb


@pytest.fixture(autouse=True)
def _reset_configured_flag():
    kb._clipboard_configured = False
    yield
    kb._clipboard_configured = False


def _run(monkeypatch, *, platform="Linux", wayland="wayland-0",
         display=":0", xclip="/usr/bin/xclip"):
    monkeypatch.setattr("platform.system", lambda: platform)
    monkeypatch.setenv("WAYLAND_DISPLAY", wayland) if wayland else \
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("DISPLAY", display) if display else \
        monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: xclip)
    fake_pyperclip = mock.MagicMock()
    monkeypatch.setitem(sys.modules, "pyperclip", fake_pyperclip)
    kb.configure_clipboard()
    return fake_pyperclip


def test_wayland_with_xwayland_prefers_xclip(monkeypatch):
    fake = _run(monkeypatch)
    fake.set_clipboard.assert_called_once_with("xclip")


def test_not_wayland_keeps_default(monkeypatch):
    fake = _run(monkeypatch, wayland=None)
    fake.set_clipboard.assert_not_called()


def test_no_xwayland_keeps_default(monkeypatch):
    fake = _run(monkeypatch, display=None)
    fake.set_clipboard.assert_not_called()


def test_no_xclip_keeps_default(monkeypatch):
    fake = _run(monkeypatch, xclip=None)
    fake.set_clipboard.assert_not_called()


def test_idempotent(monkeypatch):
    fake = _run(monkeypatch)
    kb.configure_clipboard()  # second call must not re-run selection
    fake.set_clipboard.assert_called_once()
