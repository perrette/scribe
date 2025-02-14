# Scribe

`scribe` is a local speech recognition tool that provides real-time transcription using vosk and whisper AI.

## Installation

Install PortAudio library. E.g. on Ubuntu:

```bash
sudo apt-get install portaudio19-dev
```

The python dependencies should be dealt with automatically:

```bash
git clone https://github.com/perrette/scribe.git
cd scribe
pip install -e .[all]
```
or

```bash
pip install "scribe[all] @ git+https://github.com/perrette/scribe.git"
```

You can leave the optional dependencies but must install at least one of `vosk` or `openai-whisper` packages (see Usage below).

The `vosk` language models will download on-the-fly.
The default data folder is `$HOME/.local/share/vosk/language-models`.
This can be modified.


## Usage

Just type in the terminal:

```bash
scribe
```
and the script will guide you through the choice of backend (`whisper` or `vosk`) and the specific language model.
After this, you will be prompted to start recording your microphone and print the transcribed text in real-time (`vosk`)
or until after recording is complete (`whisper`).
You can interrupt the recording via Ctrl + C and start again or change model.

The default (`whisper`) is excellent at transcribing a full-length audio sequences in [many languages](https://github.com/openai/whisper?tab=readme-ov-file#available-models-and-languages). It is really impressive,
but it cannot do real-time out of the box, and depending on the model can have relatively long execution time, especially with the `turbo` model (at least on my laptop with CPU only). The `small` model is also excellent and runs much faster. It is selected as default in `scribe` for that reason.
With the `whisker` model you need to stop the registration manually before the transcription occurs (Ctrl + C), though after
60 seconds it will stop automatically (and try to continue afterward).

The `vosk` backend is good at
doing real-time transcription for one language, but tended to make more mistakes in my tests and it does not do punctuation.
There are many [vosk models](https://alphacephei.com/vosk/models) available, and here a few are associated to [a handful of languages](scribe/models.toml) `en`, `fr`, `it`, `de` (so far).

To skip the initial selection menu you can do:
```bash
scribe --backend whisper --model small --no-prompt
```
where `--no-prompt` jumps right to the recording (after the first interruption, you can still choose to change the backend and model).

### Advanced usage as keyboard replacement

With the `--keyboard` option `scribe` will attempt to simulate a keyboard and send transcribed characters to the applcation under focus:

```bash
scribe --keyboard
```

It relies on the optional `pynput` dependency (installed together with `scribe` if you used the `[all]` or `[keyboard]` option).

`pynput` may require [some configuration](https://pynput.readthedocs.io/en/latest/limitations.html) (I *think* got it to work with `xhost +SI:localuser:$(whoami)` as far as the display is concerned). It has [limitations]((https://pynput.readthedocs.io/en/latest/limitations.html)). In my Ubuntu + Wayland system it works in chromium based applications (including vscode) but it does not in firefox and sublime text and any of the rest (not even in a terminal !).
Workarounds include using the Xorg version of GNOME... Suggestions welcome.

### Start as an application in Ubuntu

If you run Ubuntu (or else?) with GNOME, the script `scribe-install [...]` will create a `scribe.desktop` file and place it under `$HOME/.local/share/applications`
to make it available from the quick launch menu. Any option will be passed on to `scribe`.