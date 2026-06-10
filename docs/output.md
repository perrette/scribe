# Output modes

Scribe delivers transcribed text via exactly one of four
mutually-exclusive output modes, selected with the `-m / --mode` CLI
flag or the tray's **Options → Output** radio. The same four modes are
exposed in both places.

| `--mode` value          | What happens                                                                                                                                                                                                  |
|-------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `keystroke` *(default)* | Transcription lands in the focused window. **Batch models** (Whisper, Groq, OpenAI `gpt-4o-*`): single Ctrl+V at end of recording. **Streaming models** (Vosk, OpenAI `gpt-realtime-whisper`): each chunk is pasted live as it arrives — "appears as you speak". |
| `clipboard`             | Transcription copied to clipboard; you press Ctrl+V yourself.                                                                                                                                                 |
| `terminal`              | No clipboard, no keystroke — transcription is only printed to the terminal.                                                                                                                                   |
| `file`                  | Transcription appended exclusively to `--output-file`. Keyboard / clipboard output is suppressed. Defaults to `<user-desktop>/scribe-notes.txt`; override with `-o PATH`.                                     |

```bash
scribe                    # keystroke (default)
scribe --mode clipboard   # clipboard only
scribe --mode terminal    # terminal only
scribe --mode file -o transcript.txt   # file only
```

## `keystroke` — paste into the focused window (default)

In keystroke mode the transcription lands in whichever window has
focus. The mechanism inside `keystroke` mode (Ctrl+V at end vs
paste-per-chunk) is auto-picked from the active model:

- **Batch models** (Whisper, Groq, OpenAI `gpt-4o-*`) copy the full
  transcription to the clipboard and synthesise a single Ctrl+V at end
  of recording.
- **Streaming models** (Vosk, OpenAI `gpt-realtime-whisper`) paste each
  chunk live as it arrives — "appears as you speak".
- `--type-direct` (see below) bypasses the clipboard and types raw
  keystrokes instead.

Switching models via the Model menu re-evaluates the mechanism on the
next recording — no need to re-pick the radio.

> The clipboard is left holding the transcription after scribe finishes
> — if you want to preserve your previous clipboard contents, save them
> somewhere else first.

### Pasting into a terminal

Terminals (GNOME Terminal, Kitty, Alacritty, VS Code's integrated
terminal, …) don't bind plain `Ctrl+V` to paste — they interpret it as
the `^V` control character and bind paste to `Ctrl+Shift+V` instead.
Scribe always synthesises `Ctrl+V`, so the simplest workaround when
you're dictating *into a terminal* is to **hold Shift physically** at
the moment scribe fires the paste: the terminal then sees
`Ctrl+Shift+V` and pastes normally. No code change needed — just
remember Shift for terminal targets, nothing for GUI apps where plain
`Ctrl+V` already works (including VS Code's editor pane).

### Clipboard backend on Wayland

The paste path writes the clipboard through `pyperclip`, which on a
Wayland session would normally use `wl-copy`. On compositors without a
data-control protocol (GNOME < 47), `wl-copy` has to create a temporary
invisible window and briefly take keyboard focus in order to own the
selection. Most apps tolerate that focus blip, but Electron apps often
don't return focus to the input field inside the page afterwards, so
the synthesised Ctrl+V lands nowhere.

Scribe therefore prefers `xclip` whenever XWayland is available: the
clipboard is set through XWayland with no focus change, and the
compositor syncs the X and Wayland selections both ways, so every app
— X11-hosted or Wayland-native — sees the same text. The clipboard is
a single session-global resource owned by the compositor; which tool
set it is invisible to the app you paste into. When `xclip` or
XWayland is missing, scribe falls back to `wl-copy`.

### `--type-direct` — bypass the clipboard

In keystroke mode `--type-direct` (or **Options → Keyboard → Input
mode → keystroke** in the menu) types the transcription as raw
keystrokes instead of synthesising Ctrl+V. It lands in any focused
input, terminals included, without depending on a paste shortcut.

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

### Typer backends

Whichever path you take inside keystroke mode — the end-of-recording
Ctrl+V, the live per-chunk paste, or raw `--type-direct` — the actual
key events go through a *typer* backend. Scribe probes the available
backends at startup and picks the first one that works in the current
session. Backends that are *structurally incompatible* with your OS /
session are hidden from the menu entirely — the **Keyboard → Backend**
submenu only appears when there is a real choice.

| Backend  | Mechanism                            | Compatible with                                                       |
|----------|--------------------------------------|-----------------------------------------------------------------------|
| `eitype` | libei via XDG RemoteDesktop portal   | Linux Wayland (GNOME 45+, KDE Plasma 6.1+, Hyprland)                  |
| `pynput` | XTest / Quartz / WinAPI              | macOS, Windows, Linux X11 / XWayland; partial on Wayland (XWayland apps only) |
| `ydotool`| Kernel `/dev/uinput` daemon          | Linux (needs `input` group or `ydotoold` daemon)                      |
| `wtype`  | `zwp_virtual_keyboard_v1`            | wlroots-based Wayland compositors (Sway and friends — not GNOME/KDE)  |

Force a specific backend with `--typer eitype` (etc.), or pick it from
the tray / terminal menu under **Options → Keyboard → Backend**. The
selected backend's name is logged at startup so you can tell which path
your keystrokes are taking.

#### Per-OS behaviour

- **macOS / Windows** → `pynput` is the only compatible backend (Quartz
  / WinAPI, native and Unicode-correct). The Keyboard → Backend submenu
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

#### Ubuntu / Wayland caveats and recommended fix

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

### Realtime backend: delta coalescing

The `gpt-realtime-whisper` backend emits one transcription delta per
word/subword at ~30–80 ms intervals — much faster than the
`pyperclip.copy()` + Ctrl+V cycle can settle on Wayland (≥100 ms,
because `wl-copy` is asynchronous). Pasting every delta led to
clipboard races where successive copies overwrote each other before
Ctrl+V landed, manifesting as dropped and duplicated words
(*"fait fait le mot mot time time…"*).

In **paste mode** (default keystroke output) scribe therefore
coalesces deltas: incoming tokens accumulate into a small buffer and
are flushed only when *either* ~400 ms have elapsed since the last
flush, *or* the buffer ends on sentence-final punctuation
(`. ! ? \n`). A 200 ms floor between any two flushes prevents
back-to-back punctuation flushes from racing each other through the
clipboard.

With **`--type-direct`** the coalescing is bypassed entirely — each
delta goes through the chosen typer as a raw keystroke synchronously
(uinput / xtest / portal libei), no clipboard involved, no race to
defeat. The UX is also snappier: tokens appear one at a time rather
than in ~400 ms-cadenced bursts.

macOS and Windows clipboards are synchronous, so the race that
motivates coalescing is essentially a Wayland artefact; scribe still
coalesces in paste mode there for consistency, but it's harmless.
This whole behaviour is realtime-specific — Vosk's per-phrase commits
already arrive at a sane cadence, and the pseudo-streaming backends
emit one chunk per silence cut (already coarse enough).

## `clipboard` — copy to clipboard

```bash
scribe --mode clipboard
```

The transcription is copied to the system clipboard at end of recording
and you press Ctrl+V (or Ctrl+Shift+V in a terminal) yourself. No
keystrokes are synthesised, so there is no typer-backend involvement
and no Wayland portal prompt — `pyperclip` (backed by `xclip` or
`wl-copy`, see [Clipboard backend on Wayland](#clipboard-backend-on-wayland))
is all that is needed.

As with keystroke mode, the clipboard is left holding the
transcription after scribe finishes; save any previous clipboard
contents elsewhere first if you want to keep them.

## `terminal` — print only (no clipboard, no keystroke)

```bash
scribe --mode terminal
```

The transcription is printed to scribe's own stdout and nothing else
happens — the clipboard is untouched, no keystrokes are synthesised,
no file is written. Useful for piping scribe into another tool, for
debugging which text is actually being produced, or for sessions where
you just want to read the transcription off the terminal.

## `file` — write exclusively to `--output-file`

```bash
scribe --mode file                       # defaults to <Desktop>/scribe-notes.txt
scribe --mode file -o ~/dictation.txt    # override the path
```

`--mode file` appends transcribed text to the file path given by
`-o / --output-file` and suppresses every other output (no keystroke,
no clipboard copy, no terminal print). The four output modes are
mutually exclusive — there is no double-write to file + keyboard.

The `--output-file` flag defaults to the user's Desktop folder
(`platformdirs.user_desktop_dir()`, which resolves to `~/Desktop` on
Linux/macOS and `%USERPROFILE%\Desktop` on Windows; falls back to the
home directory if Desktop is absent). The default filename is
`scribe-notes.txt`. Override with any explicit `-o PATH`.

Each chunk is appended verbatim (no per-chunk newline injection — the
backend's own chunk spacing controls the file format).

From the tray, **Options → Output → Choose path…** opens a native file
picker (`tkinter`) that sets the path and switches to File mode in one
click. Picking an existing file prompts an "Append to existing file?"
confirmation (the transcription is appended, never overwritten).
If the chosen file already exists, an append-confirm dialog warns that
new chunks will be appended to it before switching modes.
