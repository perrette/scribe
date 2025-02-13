# Vosk Realtime

Vosk Realtime is a local speech recognition tool that provides real-time transcription using the Vosk package.

## Installation

Install PortAudio library. E.g. on Ubuntu:

```bash
sudo apt-get install portaudio19-dev
```

The python dependencies should be dealt with automatically:

```bash
git clone https://github.com/perrette/voskrealtime.git
cd vosk-realtime
pip install -e .
```
or

```bash
pip install git+https://github.com/perrette/voskrealtime.git
```

The language models should also download on-the-fly is not present.
The default data folder is `$HOME/.local/share/vosk/language-models`.
This can be modified.


## Usage

The `voskrealtime` script can be used as simply as:

```bash
voskrealtime --model vosk-model-en-us-0.42-gigaspeech
```
by using any of the [available vosk models](https://alphacephei.com/vosk/models).

This will prompt you for starting recording, listen to your microphone and print the transcribed text in real-time.
You can interrupt the recording via Ctrl + C and start again by pressing any key.

The [whisper](https://github.com/openai/whisper?tab=readme-ov-file#available-models-and-languages) backend is also available.It is much heavier, cannot do real-time, but is much better. You need to `openai-whisper` dependency. See the link for (very simple) install instructions. The `turbo` model is used by default.

```bash
voskrealtime --backend whisper
```

### Advanced usage as keyboard replacement:

Use `pip install -e .[keyboard]` to install the optional `pynput` dependency. pynput may require [some configuration](https://pynput.readthedocs.io/en/latest/limitations.html) (I *think* got it to work with `xhost +SI:localuser:$(whoami)` as far as the display is concerned).

```bash
voskrealtime --keyboard
```

Now the application will (should) also send the interpreted text to any application under focus (as well as the usual terminal printing). It has [limitations]((https://pynput.readthedocs.io/en/latest/limitations.html)). In my Ubuntu + Wayland system it works in chromium based applications (including vscode) but it does not in firefox and sublime text and any of the rest. Suggestions welcome.