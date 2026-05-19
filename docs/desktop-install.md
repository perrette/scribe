# Desktop entry & autostart (`scribe-install`)

On Linux (GNOME, KDE, anything supporting the freedesktop
[`.desktop`](https://specifications.freedesktop.org/desktop-entry-spec/)
spec), the `scribe-install` command generates a `scribe.desktop` file
under `$HOME/.local/share/applications` so scribe shows up in your
launcher / dash.

Any extra arguments are passed straight through to `scribe`, plus two
install-only options: `--name` (the human-readable label) and
`--frontend {tray,terminal}` (default: `tray`).

## Two common flavors

```bash
scribe-install --name "Scribe"
scribe-install --name "Scribe Terminal" --frontend terminal
```

- The first creates an app named **Scribe** that runs in tray mode
  (no terminal window), with the tray icon as the only mode of
  interaction.
- The second creates an app named **Scribe Terminal** that opens a
  terminal window and runs the interactive TUI.

Keyboard mode defaults to `keystroke` — pass `--mode clipboard` or
`--mode terminal` if you want a different default for the installed
app.

## Wayland / eitype auto-prompt

After writing the desktop file, `scribe-install` checks whether you're
on a Wayland session without `eitype` (the recommended typer backend
for GNOME / KDE / Hyprland — see [keyboard.md](keyboard.md)). If so:

- If `cargo` is already on your `$PATH`, it asks whether to run
  `cargo install --git https://github.com/Adam-D-Lewis/eitype` for you
  (~1–2 min, no `sudo`, writes only to `~/.cargo/bin`).
- If `cargo` is missing, it prints the rustup + cargo-install recipe
  so you can run it manually.

`ydotool` is never auto-installed: enabling it grants kernel-level
input access (via the `input` group or a setuid daemon) and ought to
be a conscious choice. See its package docs if you need it.
