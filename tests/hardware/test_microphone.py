# test_microphone.py
# Automatically finds a USB microphone, records audio, and saves to WAV.

import pyaudio
import wave

# --- Config ---
TARGET_KEYWORDS = ["usb", "microphone", "mic"]  # Lowercase keywords to match
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
CHUNK = 1024
RECORD_SECONDS = 5
OUTPUT_FILENAME = "test_recording.wav"

audio = pyaudio.PyAudio()

# --- Find device index ---
def find_device_index():
    matching_devices = []
    for i in range(audio.get_device_count()):
        info = audio.get_device_info_by_index(i)
        name = info.get('name', '').lower()
        if any(keyword in name for keyword in TARGET_KEYWORDS) and info.get('maxInputChannels', 0) > 0:
            matching_devices.append((i, info['name']))
    return matching_devices

devices = find_device_index()

if not devices:
    print("No matching USB microphone found. Run list_audio_devices.py to see all devices.")
    audio.terminate()
    exit(1)

# If more than one match, let user pick
if len(devices) > 1:
    print("Multiple matching devices found:")
    for idx, (dev_index, dev_name) in enumerate(devices):
        print(f"{idx}: {dev_name} (index {dev_index})")
    choice = input(f"Select device [0-{len(devices)-1}]: ")
    try:
        device_index = devices[int(choice)][0]
    except (ValueError, IndexError):
        print("Invalid choice. Exiting.")
        audio.terminate()
        exit(1)
else:
    device_index = devices[0][0]
    print(f"Using device: {devices[0][1]} (index {device_index})")

# --- Record ---
print(f"--- Starting Microphone Test ---")
print(f"Recording for {RECORD_SECONDS} seconds...")

try:
    stream = audio.open(format=FORMAT,
                        channels=CHANNELS,
                        rate=RATE,
                        input=True,
                        input_device_index=device_index,
                        frames_per_buffer=CHUNK)

    frames = []
    for _ in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
        data = stream.read(CHUNK, exception_on_overflow=False)
        frames.append(data)

    print("...Recording finished.")

    stream.stop_stream()
    stream.close()

except IOError as e:
    print(f"[ERROR] Could not open audio stream on device index {device_index}: {e}")
    audio.terminate()
    exit(1)

audio.terminate()

# --- Save to file ---
print(f"Saving recording to {OUTPUT_FILENAME}...")
wf = wave.open(OUTPUT_FILENAME, 'wb')
wf.setnchannels(CHANNELS)
wf.setsampwidth(audio.get_sample_size(FORMAT))
wf.setframerate(RATE)
wf.writeframes(b''.join(frames))
wf.close()
print("Save complete. You can now play the .wav file.")
