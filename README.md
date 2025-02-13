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
voskrealtime
```

This will prompt you for a language, listen to your microphone and print the transcribed text in real-time.

It can be extended with [any other vosk model](https://alphacephei.com/vosk/models).
Several languages and models can be passed to restrict the interactive choice menu:

```bash
voskrealtime -l fr en --model vosk-model-cn-0.22
```

Note doing Ctrl-C will exit the current model and let you start a new recording in a new language.
Mind the memory usage: every of these model adds nearly 10Gb of so RAM usage, so switching between these four will be memory intensive and bring your laptop to crash quickly. Use -l to restrict to one model at a time. Or restart the code.

### Advanced usage as keyboard replacement:

Use `pip install -e .[keyboard]` to install the optional `pynput` dependency. pynput may require [some configuration](https://pynput.readthedocs.io/en/latest/limitations.html) (I *think* got it to work with `xhost +SI:localuser:$(whoami)` as far as the display is concerned).

```bash
voskrealtime --keyboard
```

Now the application will (should) also send the interpreted text to any application under focus (as well as the usual terminal printing). It has [limitations]((https://pynput.readthedocs.io/en/latest/limitations.html)). In my Ubuntu + Wayland system it works in chromium based applications (including vscode) but it does not in firefox and sublime text and any of the rest. Suggestions welcome.