# test_microphone.py
# Description: Records a short audio clip from a specified USB microphone
# and saves it as a .wav file.

import pyaudio
import wave

# --- Configuration ---
DEVICE_INDEX = 2  # <--- IMPORTANT: CHANGE THIS to the index you found!
FORMAT = pyaudio.paInt16  # Audio format (16-bit PCM)
CHANNELS = 1  # Mono audio
RATE = 44100  # Sample rate (samples per second)
CHUNK = 1024  # Number of frames per buffer
RECORD_SECONDS = 5  # Duration of the recording
OUTPUT_FILENAME = "test_recording.wav"

# --- Main Recording Logic ---
audio = pyaudio.PyAudio()

print(f"--- Starting Microphone Test ---")
print(f"Using device index: {DEVICE_INDEX}")
print(f"Recording for {RECORD_SECONDS} seconds...")

try:
    # Start Recording Stream
    stream = audio.open(format=FORMAT,
                        channels=CHANNELS,
                        rate=RATE,
                        input=True,
                        input_device_index=DEVICE_INDEX,
                        frames_per_buffer=CHUNK)

    frames = []

    # Loop to capture audio chunks
    for i in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
        data = stream.read(CHUNK)
        frames.append(data)

    print("...Recording finished.")

    # Stop and close the stream
    stream.stop_stream()
    stream.close()

except IOError as e:
    print(f"\n[ERROR] Could not open audio stream on device index {DEVICE_INDEX}.")
    print("Please check the following:")
    print("1. Is the microphone plugged in?")
    print("2. Is the DEVICE_INDEX in the script correct? Run list_audio_devices.py to check.")
    print(f"3. System error details: {e}")

except Exception as e:
    print(f"An unexpected error occurred: {e}")

finally:
    # Terminate the PyAudio object
    audio.terminate()

# --- Save the recording to a .wav file ---
if 'frames' in locals() and frames:
    print(f"Saving recording to {OUTPUT_FILENAME}...")
    
    wf = wave.open(OUTPUT_FILENAME, 'wb')
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(audio.get_sample_size(FORMAT))
    wf.setframerate(RATE)
    wf.writeframes(b''.join(frames))
    wf.close()
    
    print("Save complete. You can now play the .wav file.")
else:
    print("No frames were recorded. File not saved.")