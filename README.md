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
voskrealtime -l fr en
```

or to use something using `custom-model` or possibly `custom-url`:

```bash
voskrealtime -l custom --custom-model vosk-model-cn-0.22
```

If you bother cloning the repo you can just edit the [config file](voskrealtime/models.toml) to add more.

This will prompt you for a language, listen to your microphone and print the transcribed text in real-time.

Note doing Ctrl-C will exit the current model and let you start a new recording in a new language.

### Advanced usage as keyboard replacement:

Use `pip install -e .[keyboard]` to install the optional `pyautogui` dependency and `pyperclip` to paste non-ascii characters. For `pyperclip` additional system libraries are required, prompted by the package. On Ubuntu: `sudo apt-get install xclip`

```bash
voskrealtime -l fr en --keyboard
```

Now the application will (should) also send keys to any application the keyboard (as well as the usual terminal printing).