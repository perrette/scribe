# Vosk Realtime

Vosk Realtime is a speech recognition tool that provides real-time transcription using the Vosk API.

## Installation

To install the necessary dependencies, run the following command:

```bash
git clone https://github.com/yourusername/vosk-realtime.git
cd vosk-realtime
pip install -e .
```
or

```bash
pip install git+https://github.com/yourusername/vosk-realtime.git
```

## Usage

Here is an example of how to use the `voskrealtime` script:

```bash
voskrealtime -l fr en
```

This will listen to your microphone and print the transcribed text in real-time.