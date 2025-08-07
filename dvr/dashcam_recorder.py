import os
import time
from pathlib import Path
from datetime import datetime
import cv2  # OpenCV for drawing text
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2 import MappedArray
from libcamera import controls

# --- Configuration ---
# Directory to save video clips
OUTPUT_DIR = Path.home() / "dashcam_videos"
# Duration of each video clip in seconds
CLIP_DURATION = 180  # 3 minutes
# Video resolution and framerate
WIDTH = 1920
HEIGHT = 1080
FRAMERATE = 30
# Video bitrate for the H.264 encoder. 10 Mbps is a good balance for 1080p.
BITRATE = 10000000

# --- Timestamp Configuration ---
TEXT_COLOR = (255, 255, 255)  # White
TEXT_SIZE = 1.2
TEXT_THICKNESS = 2
TEXT_FONT = cv2.FONT_HERSHEY_DUPLEX

def create_output_directory():
    """Create the output directory if it doesn't exist."""
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        print(f"Video clips will be saved to: {OUTPUT_DIR}")
    except OSError as e:
        print(f"Error creating directory {OUTPUT_DIR}: {e}")
        exit(1)

def apply_timestamp(request):
    """Callback function to draw the timestamp on the video frame."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with MappedArray(request, "main") as m:
        # Calculate position for the bottom-right corner
        text_width, _ = cv2.getTextSize(timestamp, TEXT_FONT, TEXT_SIZE, TEXT_THICKNESS)[0]
        position = (WIDTH - text_width - 10, HEIGHT - 10)

        # Draw the text onto the frame
        cv2.putText(m.array, timestamp, position, TEXT_FONT, TEXT_SIZE, TEXT_COLOR, TEXT_THICKNESS)

def main():
    """Main function to run the dashcam."""
    create_output_directory()

    # Initialize the camera
    picam2 = Picamera2()

    # Create a video configuration
    # The format 'XRGB8888' is required for drawing overlays with OpenCV
    video_config = picam2.create_video_configuration(
        main={"size": (WIDTH, HEIGHT), "format": "XRGB8888"},
        controls={"FrameRate": FRAMERATE}
    )
    picam2.configure(video_config)

    # Attach the timestamping function to be called before encoding each frame
    picam2.pre_callback = apply_timestamp

    print("Starting camera...")
    # Start the camera preview and processing
    picam2.start()
    time.sleep(2) # Give the camera time to adjust settings

    print("Starting dashcam loop. Press Ctrl+C to exit.")
    try:
        while True:
            # Generate a filename with the current date and time
            current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filepath = os.path.join(OUTPUT_DIR, f"{current_time}.mp4")

            print(f"Recording new clip: {filepath}")
            
            # Start recording to the file
            picam2.start_and_record_video(filepath, duration=CLIP_DURATION)

            print(f"Finished clip: {filepath}")

    except KeyboardInterrupt:
        print("\nStopping dashcam...")
    finally:
        # Ensure the camera is properly stopped on exit
        picam2.stop()
        print("Camera stopped.")

if __name__ == "__main__":
    main()
