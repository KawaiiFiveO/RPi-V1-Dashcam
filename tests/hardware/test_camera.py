# test_camera.py
# Description: Verifies that the Arducam camera module is working correctly
# using the picamera2 library. Captures a single still image.

import time
from picamera2 import Picamera2, Preview

print("Initializing camera...")

# Create a Picamera2 instance
picam2 = Picamera2()

try:
    # Create a configuration for still image capture
    # main={"size": (1920, 1080)} sets the resolution. Adjust if needed.
    camera_config = picam2.create_still_configuration(main={"size": (1920, 1080)})
    picam2.configure(camera_config)

    # Start the camera. This is necessary before capturing.
    picam2.start()
    print("Camera started. Waiting 2 seconds for sensor to adjust...")

    # The camera needs a moment to adjust its auto-exposure and white balance
    time.sleep(2)

    # Define the output filename
    output_filename = "test_image.jpg"
    print(f"Capturing image to {output_filename}...")

    # Capture the image and save it to a file
    picam2.capture_file(output_filename)

    print("Image captured successfully!")

except Exception as e:
    print(f"An error occurred: {e}")
    print("Please ensure the camera is enabled in raspi-config and connected properly.")

finally:
    # Always stop the camera to release the resource
    picam2.stop()
    print("Camera stopped.")