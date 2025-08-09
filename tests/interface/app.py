# app.py
# Description: A Flask web server that streams live video from a Raspberry Pi
# camera (like the Arducam IMX519) using the picamera2 library.

import io
import time
from threading import Condition

from flask import Flask, Response, render_template_string
from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput

# --- HTML Page Template ---
# This is the simple webpage that will be served. It contains an <img> tag
# that points to our video feed URL.
HTML_TEMPLATE = """
<html>
<head>
    <title>Raspberry Pi - Live Video Stream</title>
    <style>
        body { background-color: #333; color: #fff; font-family: sans-serif; }
        h1 { text-align: center; margin-top: 20px; }
        .video-container {
            display: flex;
            justify-content: center;
            margin-top: 20px;
        }
        img {
            border: 2px solid #555;
            border-radius: 8px;
            width: 80%;
            max-width: 1280px;
        }
    </style>
</head>
<body>
    <h1>Arducam IMX519 Live Feed</h1>
    <div class="video-container">
        <img src="{{ url_for('video_feed') }}">
    </div>
</body>
</html>
"""

# --- Streaming Output Class ---
# This class is a buffer that holds the most recent camera frame. It's
# thread-safe, which is important because the camera records in a separate
# thread from the Flask server.
class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()

# --- Flask App and Camera Initialization ---
app = Flask(__name__)
picam2 = Picamera2()
# Configure the camera for video. A resolution of 1280x720 is a good balance
# of quality and performance for streaming.
picam2.configure(picam2.create_video_configuration(main={"size": (1280, 720)}))
picam2.set_controls({"FrameRate": 30})
output = StreamingOutput()

# --- Flask Routes ---

@app.route('/')
def index():
    """Serves the main HTML page."""
    return render_template_string(HTML_TEMPLATE)

def generate_frames():
    """A generator function that yields camera frames for the video feed."""
    while True:
        with output.condition:
            # Wait until a new frame is available from the camera
            output.condition.wait()
            frame = output.frame
        
        # Yield the frame in the MJPEG format
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/video_feed')
def video_feed():
    """The route that provides the MJPEG stream."""
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

# --- Main Execution ---
if __name__ == '__main__':
    try:
        print("Starting camera recording...")
        # Start recording using the MJPEG encoder and our custom output buffer
        picam2.start_recording(MJPEGEncoder(), FileOutput(output))
        
        print("Starting Flask server...")
        # The 'threaded=True' is important to handle multiple clients
        # and the background camera recording thread.
        app.run(host='0.0.0.0', port=5000, threaded=True)
        
    except Exception as e:
        print(f"An error occurred: {e}")
        
    finally:
        print("Stopping camera recording and shutting down.")
        picam2.stop_recording()