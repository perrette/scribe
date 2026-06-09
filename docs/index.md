<!--
  Home page. The feature bullets are pulled straight from README.md (single
  source of truth) via the include-markdown plugin; everything else links into
  the guide.
-->
<p align="center">
  <img src="https://github.com/perrette/scribe/raw/main/scribe_data/share/icon.png" alt="Scribe" width="96">
</p>

# Scribe

Scribe is a speech-to-text CLI and tray app that pipes transcribed text
into the focused window. It supports local and cloud-based APIs, batch and
streaming workflows.

{%
  include-markdown "../README.md"
  start="<!-- intro-start -->"
  end="<!-- intro-end -->"
%}

<p align="center">
  <img src="https://raw.githubusercontent.com/perrette/scribe/main/docs/app-tray-menu.png" alt="Scribe tray menu" width="300">
</p>

## Get started

```bash
pip install scribe-cli[all]
scribe
```

- **[Installation](installation.md)** — PortAudio, extras, Ubuntu / GNOME tray libs, Windows.
- **[Quickstart](quickstart.md)** — your first dictation in a couple of minutes.
- **[Backends](backends.md)** — Vosk, Whisper, Whisper FUTO, OpenAI, Groq; streaming vs batch.
- **[CLI reference](cli.md)** — every `scribe --help` flag with examples.

## Guides

- [Backends in detail](backends.md) — model lists, streaming recipes, vocabulary biasing.
- [Output modes](output.md) — keystroke vs clipboard vs terminal vs file, Wayland / `eitype`, `--type-direct`.
- [System tray & global hotkeys](tray.md) — menu tree, icon states, `SIGUSR1`/`SIGUSR2`.
- [Desktop entry & autostart](desktop-install.md) — `scribe-install` launcher integration.
- [CLI reference](cli.md) — full flag reference and fine tuning.

## From the same author

A few related tools I maintain, useful in a Markdown-based scientific workflow.

**Scientific writing & data**

- [**texmark**](https://perrette.github.io/texmark/) — write scientific articles in Markdown and submit them to any journal (Markdown → LaTeX/PDF).
- [**papers**](https://perrette.github.io/papers/) — command-line BibTeX bibliography and PDF library manager.
- [**datamanifest**](https://perrette.github.io/datamanifest/) — declarative, reproducible dataset management. *(See also the [datamanifest.toml](https://perrette.github.io/datamanifest.toml/) format spec and the [DataManifest.jl](https://awi-esc.github.io/DataManifest.jl/) Julia port.)*

**Voice helpers** — handy for dictating and proofreading drafts by ear

- [**scribe**](https://perrette.github.io/scribe/) — speech-to-text dictation (Whisper).
- [**bard**](https://perrette.github.io/bard/) — text-to-speech reader (Kokoro / Piper).
