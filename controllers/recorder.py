# RPi-V1-Dashcam/controllers/recorder.py

import os
import sys
import time
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

        self.recording_thread: Optional[threading.Thread] = None
        self.recording_lock = threading.Lock()
        self.is_audio_thread_running = threading.Event()
        self.is_logging_thread_running = threading.Event()

    def _setup_camera(self):
        """
        Configures Picamera2 with an efficient stream setup:
        1. 'main': A clean, hardware-encodable YUV420 stream for high-quality recording.
        2. 'lores': A YUV420 stream for the low-lag web preview.
        """
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

    def _recording_loop(self):
        print("RECORDER: Recording loop started.")
        
        audio_thread = None
        logging_thread = None
        
        try:
            encoder = H264Encoder(bitrate=config.VIDEO_BITRATE)
            
            base_filename = datetime.now().strftime("%Y%m%d_%H%M%S")
            temp_video_path = str(config.VIDEO_DIR / f"{base_filename}.h264")
            temp_audio_path = str(config.VIDEO_DIR / f"{base_filename}.wav")
            log_path = str(config.LOG_DIR / f"{base_filename}.csv")
            final_video_path = str(config.VIDEO_DIR / f"{base_filename}.mp4")

            # --- FIX: Start video recording BEFORE audio/logging for better sync ---
            print(f"RECORDER: Recording new clip: {temp_video_path}")
            self.picam2.start_recording(encoder, temp_video_path)

            # Now start helper threads
            self.is_audio_thread_running.set()
            self.is_logging_thread_running.set()
            audio_thread = threading.Thread(target=self._record_audio_clip, args=(temp_audio_path,))
            logging_thread = threading.Thread(target=self._log_data_clip, args=(log_path,))
            audio_thread.start()
            logging_thread.start()
            
            last_split_time = time.time()

            while self.state.get_is_recording():
                if time.time() - last_split_time >= config.CLIP_DURATION_SECONDS:
                    self.is_audio_thread_running.clear()
                    self.is_logging_thread_running.clear()
                    audio_thread.join()
                    logging_thread.join()
                    
                    processing_thread = threading.Thread(
                        target=self._process_finished_clip,
                        args=(temp_video_path, temp_audio_path, final_video_path),
                        daemon=True
                    )
                    processing_thread.start()

                    base_filename = datetime.now().strftime("%Y%m%d_%H%M%S")
                    temp_video_path = str(config.VIDEO_DIR / f"{base_filename}.h264")
                    temp_audio_path = str(config.VIDEO_DIR / f"{base_filename}.wav")
                    log_path = str(config.LOG_DIR / f"{base_filename}.csv")
                    final_video_path = str(config.VIDEO_DIR / f"{base_filename}.mp4")

                    print(f"RECORDER: Splitting to new clip: {temp_video_path}")
                    self.picam2.split_recording(temp_video_path)

                    # --- FIX: Start new helper threads AFTER splitting ---
                    self.is_audio_thread_running.set()
                    self.is_logging_thread_running.set()
                    audio_thread = threading.Thread(target=self._record_audio_clip, args=(temp_audio_path,))
                    logging_thread = threading.Thread(target=self._log_data_clip, args=(log_path,))
                    audio_thread.start()
                    logging_thread.start()
                    
                    last_split_time = time.time()

                time.sleep(1)

        finally:
            if self.picam2.started:
                self.picam2.stop_recording()
                print("RECORDER: Camera encoding stopped.")

            if audio_thread and audio_thread.is_alive():
                self.is_audio_thread_running.clear()
                audio_thread.join()
            if logging_thread and logging_thread.is_alive():
                self.is_logging_thread_running.clear()
                logging_thread.join()
            
            if os.path.exists(temp_video_path):
                print("RECORDER: Processing final clip...")
                self._process_finished_clip(temp_video_path, temp_audio_path, final_video_path)

            with self.recording_lock:
                self.recording_thread = None
            print("RECORDER: Recording loop finished cleanly.")

    def _process_finished_clip(self, temp_video_path, temp_audio_path, final_video_path):
        if os.path.exists(temp_video_path):
            if self.audio_device_index is not None and os.path.exists(temp_audio_path) and os.path.getsize(temp_audio_path) > 1024:
                self._mux_video_audio(temp_video_path, temp_audio_path, final_video_path)
                os.remove(temp_audio_path)
            else:
                self._package_video_only(temp_video_path, final_video_path)
            os.remove(temp_video_path)
        else:
            print(f"RECORDER: Temp video file {temp_video_path} not found for processing.")

    def _mux_video_audio(self, video_path, audio_path, output_path):
        print(f"RECORDER: Muxing video and audio to {output_path}...")
        command = [
            'ffmpeg', '-y', '-i', video_path, '-i', audio_path,
            '-shortest',
            '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', output_path
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
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

    def _record_audio_clip(self, output_path: str):
        if self.audio_device_index is None: return
        try:
            stream = self.audio_interface.open(format=config.AUDIO_FORMAT, channels=config.AUDIO_CHANNELS, rate=config.AUDIO_RATE, input=True, input_device_index=self.audio_device_index, frames_per_buffer=config.AUDIO_CHUNK_SIZE)
            frames = []
            while self.is_audio_thread_running.is_set():
                frames.append(stream.read(config.AUDIO_CHUNK_SIZE, exception_on_overflow=False))
            stream.stop_stream(); stream.close()
            with wave.open(output_path, 'wb') as wf:
                wf.setnchannels(config.AUDIO_CHANNELS); wf.setsampwidth(self.audio_interface.get_sample_size(config.AUDIO_FORMAT)); wf.setframerate(config.AUDIO_RATE); wf.writeframes(b''.join(frames))
        except Exception as e: print(f"RECORDER: Error during audio recording: {e}")

    def _log_data_clip(self, output_path: str):
        header = ['timestamp', 'latitude', 'longitude', 'altitude', 'sats', 'speed_mph', 'v1_in_alert', 'v1_freq_ghz', 'v1_band']
        try:
            with open(output_path, 'w', newline='') as f:
                writer = csv.writer(f); writer.writerow(header)
                while self.is_logging_thread_running.is_set():
                    gps_data = self.state.get_gps_data(); v1_data = self.state.get_v1_data()
                    writer.writerow([datetime.now().isoformat(), gps_data.latitude, gps_data.longitude, gps_data.altitude, gps_data.num_sats, gps_data.speed_mph, v1_data.in_alert, v1_data.priority_alert_freq, v1_data.priority_alert_band])
                    time.sleep(config.LOGGING_INTERVAL_SECONDS)
        except Exception as e: print(f"RECORDER: Error during data logging: {e}")

    def run(self):
        print("RECORDER: Starting camera...")
        self.picam2.start()
        time.sleep(2)
        print("RECORDER: Camera ready. Waiting for commands.")
        while self.state.get_app_running():
            time.sleep(1)
        self.shutdown()

    def shutdown(self):
        print("RECORDER: Shutting down...")
        if self.recording_thread and self.recording_thread.is_alive():
            print("RECORDER: Waiting for final clip processing to complete...")
            self.stop_recording()
            self.recording_thread.join(timeout=30.0)
        if self.picam2.started:
            self.picam2.stop()
        self.audio_interface.terminate()
        print("RECORDER: Recorder shutdown complete.")