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

Here is an example of how to use the `voskrealtime` script:

```bash
voskrealtime -l fr en it de
voskrealtime -l custom --custom-model vosk-model-cn-0.22
```

If you bother cloning the repo you can just edit the [config file](voskrealtime/models.toml) to add more.

This will prompt you for a language, listen to your microphone and print the transcribed text in real-time.