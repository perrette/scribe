# Keyboard modes & typer backends

Scribe delivers transcribed text in one of three mutually-exclusive
modes, selected via the `-m / --mode` CLI flag or the tray's
**Options → Keyboard mode** radio. The same three modes are exposed in
both places.

| `--mode` value          | What happens                                                                                                                                                                                                  |
|-------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `keystroke` *(default)* | Transcription lands in the focused window. **Batch models** (Whisper, Groq, OpenAI `gpt-4o-*`): single Ctrl+V at end of recording. **Streaming models** (Vosk, OpenAI `gpt-realtime-whisper`): each chunk is pasted live as it arrives — "appears as you speak". |
| `clipboard`             | Transcription copied to clipboard; you press Ctrl+V yourself.                                                                                                                                                 |
| `terminal`              | No clipboard, no keystroke — transcription is only printed to the terminal.                                                                                                                                   |

```bash
scribe                    # keystroke (default)
scribe --mode clipboard   # clipboard only
scribe --mode terminal    # terminal only
scribe -o transcript.txt  # also append to a file (orthogonal to --mode)
```

The mechanism inside `keystroke` mode (Ctrl+V at end vs paste-per-chunk)
is auto-picked from the active model. Switching models via the Model
menu re-evaluates the mechanism on the next recording — no need to
re-pick the radio.

> The clipboard is left holding the transcription after scribe finishes
> — if you want to preserve your previous clipboard contents, save them
> somewhere else first.

## Pasting into a terminal

Terminals (GNOME Terminal, Kitty, Alacritty, VS Code's integrated
terminal, …) don't bind plain `Ctrl+V` to paste — they interpret it as
the `^V` control character and bind paste to `Ctrl+Shift+V` instead.
Scribe always synthesises `Ctrl+V`, so the simplest workaround when
you're dictating *into a terminal* is to **hold Shift physically** at
the moment scribe fires the paste: the terminal then sees
`Ctrl+Shift+V` and pastes normally. No code change needed — just
remember Shift for terminal targets, nothing for GUI apps where plain
`Ctrl+V` already works (including VS Code's editor pane).

## `--type-direct` — bypass the clipboard

In keystroke mode `--type-direct` (or **Options → Keyboard backend →
Type directly** in the menu) types the transcription as raw keystrokes
instead of synthesising Ctrl+V. It lands in any focused input,
terminals included, without depending on a paste shortcut.

Caveats:

- Slower for long text — each character is a keypress.
- Keystrokes go through the **active xkb keyboard layout**, so
  non-ASCII characters only come through if the current layout actually
  contains them. A French dictation on a French (or Italian, for shared
  accents) layout types `é` verbatim; on a US layout the same `é` is
  silently degraded to `e` via `unidecode` and a warning is logged.
- `eitype` is Unicode-correct regardless of layout; `wtype` and
  `ydotool` fall back to ASCII equivalents.

Switch your system keyboard layout to one that covers the script you're
dictating, or stick to the paste path (plain `Ctrl+V`, or the Shift
trick above) for lossless Unicode.

## Output file

An output file can also be appended to, orthogonally to `--mode`:

```bash
scribe -o transcription.txt
```

## Typer backends

Whichever mode you pick, the Ctrl+V keystroke (or live per-chunk paste,
or raw type-direct) goes through a *typer* backend. Scribe probes the
available backends at startup and picks the first one that works in the
current session. Backends that are *structurally incompatible* with
your OS / session are hidden from the menu entirely — the **Keyboard
backend** submenu only appears when there is a real choice.

| Backend  | Mechanism                            | Compatible with                                                       |
|----------|--------------------------------------|-----------------------------------------------------------------------|
| `eitype` | libei via XDG RemoteDesktop portal   | Linux Wayland (GNOME 45+, KDE Plasma 6.1+, Hyprland)                  |
| `pynput` | XTest / Quartz / WinAPI              | macOS, Windows, Linux X11 / XWayland; partial on Wayland (XWayland apps only) |
| `ydotool`| Kernel `/dev/uinput` daemon          | Linux (needs `input` group or `ydotoold` daemon)                      |
| `wtype`  | `zwp_virtual_keyboard_v1`            | wlroots-based Wayland compositors (Sway and friends — not GNOME/KDE)  |

Force a specific backend with `--typer eitype` (etc.), or pick it from
the tray / terminal menu under **Options → Keyboard backend**. The
selected backend's name is logged at startup so you can tell which path
your keystrokes are taking.

### Per-OS behaviour

- **macOS / Windows** → `pynput` is the only compatible backend (Quartz
  / WinAPI, native and Unicode-correct). The Keyboard backend submenu
  is hidden entirely — there is nothing to choose.
- **Linux X11** → `pynput` (XTest) is the natural choice; `ydotool`
  also works if you have its daemon set up. `eitype` / `wtype` are not
  applicable.
- **Linux Wayland (GNOME / KDE / Hyprland)** → `eitype` recommended;
  `pynput` available with the *XWayland apps only* caveat; `ydotool`
  as a universal fallback.
- **Linux Wayland (Sway and friends, wlroots-based)** → `wtype` works
  without setup; `eitype` not yet (no libei portal there); `pynput` /
  `ydotool` are the other fallbacks.

## Ubuntu / Wayland caveats and recommended fix

Ubuntu 24.04+ defaults to GNOME on Wayland. Without extra setup scribe
falls back to `pynput` → XTest, which lands keystrokes in
XWayland-hosted apps (most Chromium-based, including VS Code; Electron;
many GTK apps) but **not** in native Wayland clients (Firefox with
`MOZ_ENABLE_WAYLAND=1`, recent KDE apps, GNOME Console, etc.). The
symptom is "scribe says it typed something but nothing appeared".

The clean fix is to install **`eitype`**, a small CLI that speaks
[libei](https://gitlab.freedesktop.org/libinput/libei) and reaches
every modern Wayland app through the XDG RemoteDesktop portal. It is
not yet packaged by Ubuntu, so install from source via the Rust
toolchain:

```bash
# 1. Install rustup (one-line installer from https://rustup.rs)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
# follow the prompts, then either restart your shell or:
source "$HOME/.cargo/env"

# 2. Install eitype
cargo install --git https://github.com/Adam-D-Lewis/eitype
```

After installation `eitype` lives in `~/.cargo/bin/`. Scribe will pick
it up automatically on the next launch (the auto-detected backend is
printed at startup). The **first** time scribe types via eitype, your
compositor (GNOME, KDE, Hyprland — whichever you're on) will pop up
the XDG RemoteDesktop portal dialog asking for permission to "control
input devices" — accept once and the token is remembered for the
session.

> **Tip.** If you already have `cargo` installed, just running
> `scribe-install` once will detect the missing eitype and prompt to
> `cargo install` it for you. No need to copy the commands above by
> hand. See [desktop-install.md](desktop-install.md).

If `eitype` is unavailable, two older workarounds also work:

- **Xorg session.** In `/etc/gdm3/custom.conf` uncomment
  `# WaylandEnable=false` and restart. Everything goes back to working
  via `pynput` → XTest.
- **`pynput` uinput backend with root.** Requires `sudo`, the `uinput`
  kernel module, and a matching keyboard layout (e.g. French/Italian
  for `é`). With sudo you also need to preserve `HOME` and
  `XDG_RUNTIME_DIR` so the audio device list and model cache still
  resolve:

  ```bash
  sudo modprobe uinput
  sudo HOME=$HOME XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR \
       PYNPUT_BACKEND_KEYBOARD=uinput $(which scribe)
  ```

  This path only matters if you want per-character live typing through
  pynput's uinput backend specifically. The modern way is `eitype`,
  which doesn't need any of this.

Roadmap for native libei integration (eventual Python bindings,
expanded compositor support) is tracked in
[docs/roadmap-libei.md](roadmap-libei.md).
