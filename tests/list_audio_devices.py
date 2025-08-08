# list_audio_devices.py
# Description: Lists all available audio input and output devices
# that PyAudio can see, along with their device index.

import pyaudio

p = pyaudio.PyAudio()

print("--- Audio Device Information ---")
info = p.get_host_api_info_by_index(0)
num_devices = info.get('deviceCount')

for i in range(0, num_devices):
    device_info = p.get_device_info_by_host_api_device_index(0, i)
    if device_info.get('maxInputChannels') > 0:
        print(f"Input Device ID {i} - {device_info.get('name')}")

print("------------------------------")
p.terminate()