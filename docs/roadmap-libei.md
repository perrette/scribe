# Roadmap: native Wayland keyboard injection via libei

**Status:** proposed, not started
**Owner:** @perrette
**Tracking memory:** [[project-scribe-roadmap-2026]]

## Goal

Make scribe's "type the transcription into the focused app" path work natively
on modern Wayland sessions (GNOME, KDE, Hyprland) without root, without an
`input`-group daemon, and without reboot — replacing today's pynput + XTest
path that only works on X11 / XWayland.

## Why now

- Ubuntu 25.10 ships GNOME Wayland by default; the X11 fallback is gone.
- Two reference voice apps surveyed in 2026 (voxd, hyprvoice) both punt on
  this — they shell out to `ydotool` (uinput, needs daemon + reboot) or
  `wtype` (wlroots-only). Neither works seamlessly on Ubuntu GNOME.
- **libei** (Peter Hutterer / freedesktop, 1.0 in mid-2023) is now the
  cross-compositor input-emulation protocol. It rides through the XDG
  RemoteDesktop portal, so it inherits the portal's consent UX and works on
  any compositor that has implemented EIS.

## Current state (2026-05)

scribe has two output paths into the focused app:

1. **Clipboard + auto-paste** (the new default since this roadmap landed).
   Writes the transcription to the clipboard via `pyperclip`, then
   synthesizes Ctrl+V via `pynput`. The Ctrl+V keystroke goes through XTest,
   so it only lands in apps that accept XWayland input (most Electron /
   Chromium / GTK apps default to XWayland on Ubuntu; native-Wayland-only
   apps like Firefox-with-MOZ_ENABLE_WAYLAND or recent KDE apps may drop
   it).
2. **Per-character typing** (`--keyboard`). Same XTest limitation, with the
   added pain of layout-dependent character handling and 100+ keystrokes
   per utterance.

Both paths live in [`scribe/keyboard.py`](../scribe/keyboard.py).

## Target architecture

A pluggable `Typer` abstraction with runtime backend selection, similar to
hyprvoice's `internal/injection/` chain but with libei as a first-class
backend:

```
scribe/keyboard.py
    Typer (protocol)
        .type(text: str) -> None
        .paste() -> None           # synthesize Ctrl+V on whatever backend
        .available() -> bool       # probe

    EitypeTyper   — subprocess → `eitype` CLI (libei via RemoteDesktop portal)
    PynputTyper   — current XTest path (X11 / XWayland fallback)
    WtypeTyper    — `wtype` CLI (wlroots / Sway / Hyprland fallback)
    YdotoolTyper  — `ydotool` CLI (last resort, requires daemon)

    pick_typer()  — probes in order: eitype → pynput (if $DISPLAY) → wtype
                    (if $WAYLAND_DISPLAY) → ydotool → raise
```

The existing `paste=True` flow in `type_text()` keeps working — it just
delegates `paste_text()` to `Typer.paste()`.

## Compatibility matrix (as of mid-2026)

| Compositor / session       | libei (eitype) | pynput XTest | wtype | ydotool |
|-----------------------------|:--------------:|:------------:|:-----:|:-------:|
| X11                         |       —        |      ✅      |   —   |   ✅    |
| GNOME Wayland (Ubuntu 24+)  |      ✅        |   XWayland   |   ❌  |   ✅¹   |
| KDE Plasma 6.1+ Wayland     |      ✅        |   XWayland   |   ❌  |   ✅¹   |
| Hyprland                    |      ✅        |   XWayland   |   ✅  |   ✅¹   |
| Sway / stock wlroots        |      ❌²       |   XWayland   |   ✅  |   ✅¹   |
| macOS                       |       —        |      ✅      |   —   |   —     |

¹ Requires `input` group + `ydotoold` daemon. Not a "seamless" backend.
² `xdg-desktop-portal-wlr#323` still open — libei not yet supported there.

## Implementation plan

### Phase 1 — Refactor existing code into a Typer abstraction

No new functionality; pure refactor so that subsequent phases plug in cleanly.

- Extract `Typer` protocol + `PynputTyper` from
  [`scribe/keyboard.py`](../scribe/keyboard.py).
- Move `paste_text()` and `safe_type_text()` into `PynputTyper`.
- `type_text(...)` becomes a thin facade that resolves a typer via
  `pick_typer()` and delegates. Keep the public signature unchanged so
  callers in `app.py` don't move.
- Add a `--typer {auto,eitype,pynput,wtype,ydotool}` CLI flag (default
  `auto`) for debugging / forcing a backend.

### Phase 2 — Add `EitypeTyper` (subprocess)

- Detect the `eitype` binary on `$PATH`. If absent, this backend is
  unavailable.
- `EitypeTyper.type(text)` → `subprocess.run(["eitype", "--", text],
  check=True)`.
- `EitypeTyper.paste()` → `subprocess.run(["eitype", "-M", "ctrl", "v"])`.
- The first invocation per session triggers the XDG RemoteDesktop portal
  consent dialog. Surface this in the README so users aren't surprised by
  a "scribe wants to control your input" pop-up.
- Document install: `cargo install eitype` (no distro packages yet as of
  2026-05). Optional: add a `scribe-install --with-eitype` helper that
  shells out to cargo.

### Phase 3 — Fallback chain

Wire `pick_typer()` to probe eitype → pynput → wtype → ydotool, with the
matrix above. Log which backend was chosen at startup so users can debug
"why doesn't my Ctrl+V land" without strace.

### Phase 4 (optional, later) — Native bindings

Replace the `eitype` subprocess with one of:

- **`snegg`** — Hutterer's own Python bindings to libei/libeis/liboeffis.
  Author explicitly calls the API "nowhere near stable" as of 2026-05.
  Not yet.
- **`eitype` Python bindings** — `pyo3` bindings shipped alongside the
  Rust CLI. More stable surface than snegg, smaller dependency than the
  subprocess + cargo route.

Defer until one of these stabilizes; the subprocess path is fine for
shipping today.

## Known caveats / open questions

- **Portal consent UX.** First-run dialog says "control input devices" which
  looks scary for a dictation tool. Investigate whether we can persist a
  portal token across sessions (the spec supports it; depends on
  `xdg-desktop-portal` version).
- **Password fields.** EIS servers may silently drop events when a password
  field or lockscreen is focused. Good for security, bad for "where did my
  text go?". scribe cannot detect this — document it.
- **Unicode + layout drift.** libei sends evdev keycodes; the compositor's
  xkb layout decides the produced character. For arbitrary Unicode (emoji,
  CJK) we may need to keep the clipboard-paste path as the primary route
  and use `eitype` only for the Ctrl+V keystroke.
- **Flatpak.** If scribe ever ships as Flatpak, the portal route is the
  *only* route — direct EIS sockets won't work in the sandbox.
- **Sway/wlroots gap.** No libei there yet; users stay on `wtype` (or
  pynput via XWayland) until `xdg-desktop-portal-wlr#323` lands.

## References

- [libei API docs](https://libinput.pages.freedesktop.org/libei/api/index.html)
- [Phoronix: libei 1.0 released](https://www.phoronix.com/news/libei-1.0-Emulated-Input)
- [eitype (Adam-D-Lewis)](https://github.com/Adam-D-Lewis/eitype)
- [snegg announcement (who-t.blogspot.com)](http://who-t.blogspot.com/2023/06/snegg-python-bindings-for-libei.html)
- [XDG RemoteDesktop portal spec](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html)
- [xdg-desktop-portal-wlr#323 — libei support](https://github.com/emersion/xdg-desktop-portal-wlr/issues/323)
- Reference voice apps surveyed: [voxd](https://github.com/jakovius/voxd),
  [hyprvoice](https://github.com/LeonardoTrapani/hyprvoice). Both shell out
  to `ydotool` / `wtype`; neither uses libei yet.
