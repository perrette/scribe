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
pip install -e .[vosk,whisper,keyboard]
```
or

```bash
pip install "scribe[vosk,whisper,keyboard] @ git+https://github.com/perrette/scribe.git"
```

You can leave the optional dependencies but must install at least one of `vosk` or `whisper`.

The `vosk` language models should also download on-the-fly if not present.
The default data folder is `$HOME/.local/share/vosk/language-models`.
This can be modified.


## Usage

The `scribe` uses vosk by defaut (when both packages are installed). It can be used as simply as:

```bash
scribe --model vosk-model-en-us-0.42-gigaspeech
```
by using any of the [available vosk models](https://alphacephei.com/vosk/models). Or a one of the few [pre-defined languages](scribe/models.toml) `en`, `fr`, `it`, `de` so far:

```bash
scribe -l en
```

This will prompt you for starting recording, listen to your microphone and print the transcribed text in real-time.
You can interrupt the recording via Ctrl + C and start again by pressing any key.

The [whisper](https://github.com/openai/whisper?tab=readme-ov-file#available-models-and-languages) backend is also available. It is much heavier, cannot do real-time, but it is so much better as I write. You need to `openai-whisper` dependency. See the link for (very simple) install instructions. The `turbo` model is used by default, which can deal with any language.

```bash
scribe --backend whisper
```

Here you need to automatically stop the registration before the transcription occurs, though after
60 seconds it will stop automatically (and try to continue afterward). It takes around 10s or up to a minute to do the transcription with the default `turbo` model on my laptop.

### Advanced usage as keyboard replacement:

Use `pip install -e .[keyboard]` to install the optional `pynput` dependency. pynput may require [some configuration](https://pynput.readthedocs.io/en/latest/limitations.html) (I *think* got it to work with `xhost +SI:localuser:$(whoami)` as far as the display is concerned).

```bash
scribe --keyboard
```

Now the application will (should) also send the interpreted text to any application under focus (as well as the usual terminal printing). It has [limitations]((https://pynput.readthedocs.io/en/latest/limitations.html)). In my Ubuntu + Wayland system it works in chromium based applications (including vscode) but it does not in firefox and sublime text and any of the rest. Suggestions welcome.