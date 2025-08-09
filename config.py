# RPi-V1-Dashcam/config.py

import pyaudio
from pathlib import Path

# -----------------------------------------------------------------------------
# --- General & Path Configuration ---
# -----------------------------------------------------------------------------
# The base directory of the project.
BASE_DIR = Path(__file__).resolve().parent

# Main directory for storing all output files.
RECORDINGS_DIR = BASE_DIR / "recordings"

# Subdirectory for final video clips (.mp4).
VIDEO_DIR = RECORDINGS_DIR / "videos"

# Subdirectory for data logs (.csv) that correspond to each video clip.
LOG_DIR = RECORDINGS_DIR / "logs"

# -----------------------------------------------------------------------------
# --- Video Recording Configuration ---
# -----------------------------------------------------------------------------
# Video resolution. 1920x1080 is 1080p. 1280x720 is 720p.
VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080

# Frames per second for video recording.
VIDEO_FRAMERATE = 30

# Video bitrate for the H.264 encoder. Higher values mean better quality
# and larger file sizes. 10,000,000 (10 Mbps) is a good starting point for 1080p.
VIDEO_BITRATE = 10000000

# Duration of each video clip in seconds. (e.g., 180 = 3 minutes).
CLIP_DURATION_SECONDS = 180

# -----------------------------------------------------------------------------
# --- Audio Recording Configuration ---
# -----------------------------------------------------------------------------
# Keywords to help automatically find the USB microphone.
# The script will look for device names containing any of these (case-insensitive).
AUDIO_DEVICE_KEYWORDS = ["usb", "microphone", "mic"]

# Audio recording format. paInt16 is standard CD quality.
AUDIO_FORMAT = pyaudio.paInt16

# Number of audio channels. 1 for mono, 2 for stereo.
AUDIO_CHANNELS = 1

# Sample rate in Hz. 44100 is standard for audio.
AUDIO_RATE = 44100

# The number of frames per buffer. A power of 2 is common.
AUDIO_CHUNK_SIZE = 4096

# -----------------------------------------------------------------------------
# --- GPS Module Configuration ---
# -----------------------------------------------------------------------------
# The serial port the GPS module is connected to.
# On Raspberry Pi 3/4/Zero W, this is typically "/dev/serial0".
# On older Pis or with USB GPS, it might be "/dev/ttyAMA0" or "/dev/ttyUSB0".
GPS_SERIAL_PORT = "/dev/serial0"

# The baud rate for the serial communication with the GPS module.
# 9600 is the most common default for NEO-6M modules.
GPS_BAUD_RATE = 9600

# -----------------------------------------------------------------------------
# --- OLED Display Configuration ---
# -----------------------------------------------------------------------------
# The I2C port number the OLED is connected to.
OLED_I2C_PORT = 1

# The I2C address of the OLED display. 0x3C is the most common.
OLED_I2C_ADDRESS = 0x3C

# The dimensions of the OLED display in pixels.
OLED_WIDTH = 128
OLED_HEIGHT = 32

# -----------------------------------------------------------------------------
# --- Valentine One BLE Configuration ---
# -----------------------------------------------------------------------------
# Bluetooth Service and Characteristic UUIDs for V1connection LE.
# These are fixed and should not be changed.
V1_SERVICE_UUID = "92A0AFF4-9E05-11E2-AA59-F23C91AEC05E"
V1_WRITE_CHAR_UUID = "92A0B6D4-9E05-11E2-AA59-F23C91AEC05E"
V1_NOTIFY_CHAR_UUID = "92A0B2CE-9E05-11E2-AA59-F23C91AEC05E"

# -----------------------------------------------------------------------------
# --- Web Interface Configuration ---
# -----------------------------------------------------------------------------
# The host address for the Flask web server.
# '0.0.0.0' makes it accessible from any device on the same network.
WEB_SERVER_HOST = '0.0.0.0'

# The port for the Flask web server.
WEB_SERVER_PORT = 5000

# Default camera rotation in degrees. Only 0 and 180 are supported.
VIDEO_ROTATION = 0

# --- Live Preview Configuration ---
# A lower resolution for the web preview stream to reduce lag.
# 640x360 maintains a 16:9 aspect ratio.
PREVIEW_WIDTH = 640
PREVIEW_HEIGHT = 360

# --- Data Logging Configuration ---
# Interval in seconds to write a new row to the data log.
# 1.0 = 1 Hz, 0.5 = 2 Hz, 0.2 = 5 Hz.
LOGGING_INTERVAL_SECONDS = 0.2