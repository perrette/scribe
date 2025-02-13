import sounddevice as sd
import queue


def get_duration(audio_length_bytes, # bytes
                sampling_rate = 16000,  # Hz
                num_channels = 1,  # Mono
                sample_width = 2,  # 16-bit audio
                ):

    # Calculate the number of samples
    num_samples = audio_length_bytes / (num_channels * sample_width)

    # Calculate the duration in seconds
    duration_seconds = num_samples / sampling_rate

    return duration_seconds


class Microphone:
    def __init__(self,
            samplerate = 16000,  # Vosk models typically use a 16kHz sample rate
            channels = 1,  # Mono audio
            device = None,  # Default device
            dtype = 'int16',  # Vosk models typically use 16-bit audio
        ):
        self.q = queue.Queue()
        self.samplerate = samplerate
        self.channels = channels
        self.device = device
        self.dtype = dtype

    # Fonction callback pour traiter les morceaux audio
    def callback(self, indata, frames, time, status):
        if status:
            print(status)
        self.q.put(bytes(indata))
        # if frames > 1000:  # Ajustez cette valeur pour essayer différents morceaux de taille
    #     rec.AcceptWaveform(bytes(indata))


    def open_stream(self):
        self.q.queue.clear()
        return sd.InputStream(samplerate=self.samplerate, device=self.device,
                              channels=self.channels, callback=self.callback, dtype=self.dtype)

    def device_info(self):
        return sd.query_devices(self.device, 'input')

    def get_duraction(self, audio_length_bytes):
        return get_duration(audio_length_bytes, self.samplerate, self.channels, {'int16':2}[self.dtype])