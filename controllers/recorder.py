# RPi-V1-Dashcam/controllers/recorder.py

import os
import sys
import time
#import cv2
import pyaudio
import wave
import csv
import subprocess
import threading
from datetime import datetime
from typing import Optional

from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import FileOutput
from picamera2 import MappedArray
from libcamera import controls
import libcamera

# Import shared application components
from shared_state import AppState
import config

class Recorder:
    def __init__(self, state: AppState):
        self.state = state
        self.picam2 = Picamera2()
        
        null_fd = os.open(os.devnull, os.O_WRONLY)
        save_stderr = os.dup(2)
        try:
            os.dup2(null_fd, 2)
            self.audio_interface = pyaudio.PyAudio()
        finally:
            os.dup2(save_stderr, 2)
            os.close(null_fd)
            os.close(save_stderr)
        
        self.audio_device_index = self._find_audio_device()
        self._setup_camera()

        # --- Internal state for the new state machine ---
        self._is_currently_recording = False
        self._recording_lock = threading.Lock()

    def _setup_camera(self):
        print("RECORDER: Configuring camera with optimized stream formats...")
        hflip = (config.VIDEO_ROTATION == 180)
        vflip = (config.VIDEO_ROTATION == 180)
        video_config = self.picam2.create_video_configuration(
            main={"size": (config.VIDEO_WIDTH, config.VIDEO_HEIGHT), "format": "YUV420"},
            lores={"size": (config.PREVIEW_WIDTH, config.PREVIEW_HEIGHT), "format": "YUV420"},
            transform=libcamera.Transform(hflip=hflip, vflip=vflip),
            controls={
                "FrameRate": config.VIDEO_FRAMERATE,
                "AeConstraintMode": controls.AeConstraintModeEnum.Normal,
                "AeEnable": True,
            }
        )
        self.picam2.configure(video_config)
        print(f"RECORDER: Camera configured with {config.VIDEO_ROTATION}-degree rotation.")

    def _find_audio_device(self) -> Optional[int]:
        print("RECORDER: Searching for audio device...")
        for i in range(self.audio_interface.get_device_count()):
            info = self.audio_interface.get_device_info_by_index(i)
            name = info.get('name', '').lower()
            if info.get('maxInputChannels', 0) > 0 and any(k in name for k in config.AUDIO_DEVICE_KEYWORDS):
                print(f"RECORDER: Found audio device: {info['name']} (index {i})")
                return i
        print("RECORDER: WARNING - No matching USB microphone found. Audio will not be recorded.")
        return None

    def start_recording(self) -> bool:
        with self.recording_lock:
            if self.recording_thread and self.recording_thread.is_alive():
                return False
            self.state.set_is_recording(True)
            self.recording_thread = threading.Thread(target=self._recording_loop, daemon=True)
            self.recording_thread.start()
            return True

    def stop_recording(self) -> bool:
        with self.recording_lock:
            if not (self.recording_thread and self.recording_thread.is_alive()):
                return False
            self.state.set_is_recording(False)
            return True

    # --- The web app now only calls these simple flag setters ---
    def start_recording(self) -> bool:
        """Signals the recorder's main loop to start recording."""
        if self.state.get_is_recording():
            return False # Already signaled to record
        print("RECORDER: Received start recording signal.")
        self.state.set_is_recording(True)
        return True

    def stop_recording(self) -> bool:
        """Signals the recorder's main loop to stop recording."""
        if not self.state.get_is_recording():
            return False # Already signaled to stop
        print("RECORDER: Received stop recording signal.")
        self.state.set_is_recording(False)
        return True

    def _record_clip(self):
        """
        This function now records exactly ONE clip and then returns.
        It is called repeatedly by the main run() loop.
        """
        with self._recording_lock:
            if not self.state.get_is_recording():
                return # Stop signal received before we could start

            base_filename = datetime.now().strftime("%Y%m%d_%H%M%S")
            temp_video_path = str(config.VIDEO_DIR / f"{base_filename}.h264")
            temp_audio_path = str(config.VIDEO_DIR / f"{base_filename}.wav")
            log_path = str(config.LOG_DIR / f"{base_filename}.csv")
            final_video_path = str(config.VIDEO_DIR / f"{base_filename}.mp4")

            audio_thread = None
            logging_thread = None
            
            try:
                print(f"RECORDER: Starting new clip: {temp_video_path}")
                encoder = H264Encoder(bitrate=config.VIDEO_BITRATE)
                self.picam2.start_encoder(encoder, output=temp_video_path, name="main")
                self._is_currently_recording = True

                is_audio_thread_running = threading.Event()
                is_logging_thread_running = threading.Event()
                is_audio_thread_running.set()
                is_logging_thread_running.set()

                audio_thread = threading.Thread(target=self._record_audio_segment, args=(temp_audio_path, is_audio_thread_running))
                logging_thread = threading.Thread(target=self._log_data_segment, args=(log_path, is_logging_thread_running))
                audio_thread.start()
                logging_thread.start()

                start_time = time.time()
                while time.time() - start_time < config.CLIP_DURATION_SECONDS:
                    if not self.state.get_is_recording():
                        print("RECORDER: Stop signal detected, ending clip early.")
                        break
                    if not audio_thread.is_alive() or not logging_thread.is_alive():
                        print("RECORDER: Helper thread died, ending clip early.")
                        break
                    time.sleep(1)

            finally:
                print("RECORDER: Finalizing clip.")
                self.picam2.stop_encoder(name="main")
                self._is_currently_recording = False

                if audio_thread:
                    is_audio_thread_running.clear()
                    audio_thread.join(timeout=5.0)
                if logging_thread:
                    is_logging_thread_running.clear()
                    logging_thread.join(timeout=5.0)

                if os.path.exists(temp_video_path):
                    self._process_finished_clip(temp_video_path, temp_audio_path, final_video_path)

    def _process_finished_clip(self, temp_video_path, temp_audio_path, final_video_path):
        # --- Signal start of processing ---
        self.state.add_processing_file(os.path.basename(final_video_path), 'muxing')
        try:
            if os.path.exists(temp_video_path):
                if self.audio_device_index is not None and os.path.exists(temp_audio_path) and os.path.getsize(temp_audio_path) > 1024:
                    self._mux_video_audio(temp_video_path, temp_audio_path, final_video_path)
                    os.remove(temp_audio_path)
                else:
                    self._package_video_only(temp_video_path, final_video_path)
                os.remove(temp_video_path)
            else:
                print(f"RECORDER: Temp video file {temp_video_path} not found for processing.")
        finally:
            # --- Signal end of processing, even if an error occurred ---
            self.state.remove_processing_file(os.path.basename(final_video_path))

    def _mux_video_audio(self, video_path, audio_path, output_path):
        print(f"RECORDER: Muxing video and audio to {output_path}...")
        command = [
            'ffmpeg', '-y', '-i', video_path, '-i', audio_path,
            '-shortest',
            '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', output_path
        ]
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            print(f"RECORDER: Muxing complete for {output_path}")
        except subprocess.CalledProcessError as e:
            print(f"RECORDER: ERROR - ffmpeg muxing failed. STDERR: {e.stderr}")

    def _package_video_only(self, video_path, output_path):
        print(f"RECORDER: Packaging video-only to {output_path}...")
        command = ['ffmpeg', '-y', '-framerate', str(config.VIDEO_FRAMERATE), '-i', video_path, '-c:v', 'copy', output_path]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
            print(f"RECORDER: Packaging complete for {output_path}")
        except subprocess.CalledProcessError as e:
            print(f"RECORDER: ERROR - ffmpeg packaging failed. STDERR: {e.stderr}")

    def _record_audio_segment(self, output_path: str, running_event: threading.Event):
        if self.audio_device_index is None: return
        stream = None
        try:
            stream = self.audio_interface.open(format=config.AUDIO_FORMAT, channels=config.AUDIO_CHANNELS, rate=config.AUDIO_RATE, input=True, input_device_index=self.audio_device_index, frames_per_buffer=config.AUDIO_CHUNK_SIZE)
            frames = []
            while self.is_audio_thread_running.is_set():
                frames.append(stream.read(config.AUDIO_CHUNK_SIZE, exception_on_overflow=False))
            
            with wave.open(output_path, 'wb') as wf:
                wf.setnchannels(config.AUDIO_CHANNELS)
                wf.setsampwidth(self.audio_interface.get_sample_size(config.AUDIO_FORMAT))
                wf.setframerate(config.AUDIO_RATE)
                wf.writeframes(b''.join(frames))
        except Exception as e:
            print(f"RECORDER: CRITICAL ERROR during audio recording: {e}")
        finally:
            if stream:
                stream.stop_stream()
                stream.close()
            print("RECORDER: Audio recording thread finished.")

    def _log_data_segment(self, output_path: str, running_event: threading.Event):
        # --- ADD NEW HEADERS ---
        header = [
            'timestamp', 'latitude', 'longitude', 'altitude', 'sats', 'speed_mph', 
            'v1_in_alert', 'v1_freq_ghz', 'v1_band', 'v1_direction', 'v1_strength'
        ]
        try:
            with open(output_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(header)
                while self.is_logging_thread_running.is_set():
                    gps_data = self.state.get_gps_data()
                    v1_data = self.state.get_v1_data()
                    # --- ADD NEW DATA TO THE ROW ---
                    writer.writerow([
                        datetime.now().isoformat(), 
                        gps_data.latitude, gps_data.longitude, gps_data.altitude, 
                        gps_data.num_sats, gps_data.speed_mph, 
                        v1_data.in_alert, v1_data.priority_alert_freq, v1_data.priority_alert_band,
                        v1_data.priority_alert_direction, v1_data.priority_alert_strength
                    ])
                    time.sleep(config.LOGGING_INTERVAL_SECONDS)
        except Exception as e:
            print(f"RECORDER: CRITICAL ERROR during data logging: {e}")
        finally:
            print("RECORDER: Data logging thread finished.")

    def run(self):
        """The main state machine loop for the entire Recorder controller."""
        print("RECORDER: Starting camera and entering main control loop...")
        self.picam2.start()
        
        # --- FIX: Start the MJPEG encoder in a NON-BLOCKING way ---
        mjpeg_encoder = MJPEGEncoder()
        streaming_output = self.state.get_streaming_output()
        lores_output = FileOutput(streaming_output)
        self.picam2.start_encoder(mjpeg_encoder, lores_output, name="lores")
        print("RECORDER: MJPEG encoder for live preview started on 'lores' stream.")

        while self.state.get_app_running():
            should_be_recording = self.state.get_is_recording()

            with self._lock:
                is_thread_running = self._clip_thread and self._clip_thread.is_alive()

            if should_be_recording and not is_thread_running:
                # State wants to record, but our clip thread isn't running. Start it.
                print("RECORDER: State machine is starting the clip recording thread.")
                self._clip_thread = threading.Thread(target=self._clip_recording_loop, daemon=True)
                self._clip_thread.start()
            
            time.sleep(1) # Main loop polling interval

        print("RECORDER: Shutdown signal received.")
        self.shutdown()

    def shutdown(self):
        """Gracefully shuts down the recorder."""
        print("RECORDER: Shutting down...")
        # Signal the clip loop to stop
        self.state.set_is_recording(False)
        
        # --- FIX: Wait for the clip thread to finish, if it exists ---
        with self._lock:
            clip_thread_to_join = self._clip_thread

        if clip_thread_to_join and clip_thread_to_join.is_alive():
            print("RECORDER: Waiting for final clip to finish processing...")
            clip_thread_to_join.join(timeout=30.0) # Generous timeout
        
        if self.picam2.started:
            print("RECORDER: Stopping camera system.")
            self.picam2.stop()
        
        self.audio_interface.terminate()
        print("RECORDER: Recorder shutdown complete.")
