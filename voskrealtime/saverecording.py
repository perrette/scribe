import sounddevice as sd
import time
import numpy as np
from pydub import AudioSegment
import io

# Set up the audio parameters
samplerate = 16000  # Vosk models typically use 16 kHz
channels = 1
duration = 5  # in seconds
chunk_size = 1024  # Number of samples per chunk (adjust this based on your needs)

# Create a numpy array to store the full audio buffer
full_audio = np.zeros((0,), dtype=np.float32)  # Use float32 initially for better precision

# Callback function to collect audio data into the buffer
def callback(indata, frames, time, status):
    if status:
        print(status)
    global full_audio
    # Append the incoming data to the full audio buffer (in float32)
    full_audio = np.concatenate((full_audio, indata[:, 0]))

# Function to record audio for a fixed duration
def record_for_duration(duration):
    try:
        with sd.InputStream(samplerate=samplerate, channels=channels, callback=callback):
            print(f"Recording for {duration} seconds or interrupt with Ctrl-C")
            sd.sleep(duration * 1000)  # Sleep for the duration to ensure we record for the fixed time
    except KeyboardInterrupt:
        pass
    print("Recording finished.")
    save_audio_as_mp3()

# Function to save the recorded audio as an MP3 file
def save_audio_as_mp3():
    # Convert the float32 audio buffer to 16-bit PCM (this is required for conversion to MP3)
    audio_16bit = np.int16(full_audio * 32767)  # Scale to the 16-bit range
    
    # Create an in-memory audio file using io.BytesIO
    audio_data = io.BytesIO()
    
    # Save the audio as WAV using pydub (since pydub works with WAV directly)
    # Convert the numpy array to a pydub AudioSegment
    audio_segment = AudioSegment(
        audio_16bit.tobytes(),
        frame_rate=samplerate,
        sample_width=2,  # 16-bit audio
        channels=1
    )
    
    # Export as MP3`
    audio_segment.export(audio_data, format="mp3")
    
    # Save to a file
    with open("recording.mp3", "wb") as f:
        f.write(audio_data.getvalue())
    print("Recording saved as recording.mp3")

# Example: record for 5 seconds
record_for_duration(5*60)

