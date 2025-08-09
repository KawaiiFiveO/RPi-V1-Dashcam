# RPi-V1-Dashcam/utils/post_processing.py

import subprocess
import pandas as pd
from datetime import datetime
import tempfile
import os

# Import config to get the logging interval for the overlay duration
import config

def _escape_ffmpeg_text(text: str) -> str:
    """
    Escapes special characters in a string for use in an ffmpeg drawtext filter.
    Characters that need escaping include: ' : , [ ] \
    """
    text = text.replace('\\', '\\\\\\\\') # Must escape backslash for filter file
    text = text.replace("'", r"\'")
    text = text.replace(':', r'\:')
    text = text.replace(',', r'\,')
    text = text.replace('[', r'\[')
    text = text.replace(']', r'\]')
    return text

def burn_in_data(video_path: str, log_path: str):
    """
    Reads a CSV log file and burns the data as a text overlay onto the
    corresponding video file using ffmpeg. This version uses a complex filtergraph
    to correctly handle video filtering alongside audio stream copying.
    """
    print(f"POST-PROCESS: Starting burn-in for {video_path}")
    
    filter_script_file = None
    try:
        log_data = pd.read_csv(log_path, parse_dates=['timestamp'])
        if log_data.empty:
            print("POST-PROCESS: Log file is empty. Aborting.")
            return

        start_time = log_data['timestamp'].iloc[0]
        filters = []
        
        # --- Filter for GPS Data ---
        gps_entries = log_data[log_data['latitude'] != 0.0]
        for _, row in gps_entries.iterrows():
            time_offset = (row['timestamp'] - start_time).total_seconds()
            end_offset = time_offset + config.LOGGING_INTERVAL_SECONDS
            gps_text = f"GPS: {row['latitude']:.4f}, {row['longitude']:.4f} | Sats: {int(row['sats'])} | Speed: {row['speed_mph']:.0f} MPH"
            escaped_gps_text = _escape_ffmpeg_text(gps_text)
            
            filters.append(
                f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
                f"text='{escaped_gps_text}':"
                f"x=10:y=10:"
                f"fontsize=24:fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=5:"
                f"enable='between(t,{time_offset},{end_offset})'"
            )

        # --- Filter for V1 Alert Data ---
        alert_entries = log_data[log_data['v1_in_alert'] == True]
        for _, row in alert_entries.iterrows():
            time_offset = (row['timestamp'] - start_time).total_seconds()
            end_offset = time_offset + config.LOGGING_INTERVAL_SECONDS
            alert_text = f"V1 ALERT: {row['v1_band']} / {row['v1_freq_ghz']:.3f} GHz"
            escaped_alert_text = _escape_ffmpeg_text(alert_text)

            filters.append(
                f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
                f"text='{escaped_alert_text}':"
                f"x=10:y=h-th-10:"
                f"fontsize=28:fontcolor=yellow:box=1:boxcolor=black@0.5:boxborderw=5:"
                f"enable='between(t,{time_offset},{end_offset})'"
            )

        if not filters:
            print("POST-PROCESS: No data to burn in. Aborting.")
            return

        filter_chain = ",".join(filters)
        
        # --- FIX: Construct a -filter_complex argument ---
        # [0:v] is the video from the first input. We apply our filter chain to it.
        # [v] is the label for the resulting filtered video stream.
        # We also select the audio stream [0:a] to pass it through.
        filter_complex_arg = f"[0:v]{filter_chain}[v];[0:a]acopy[a]"

        output_path = video_path.replace('.mp4', '_processed.mp4')
        
        # --- FIX: The new, robust ffmpeg command ---
        command = [
            'ffmpeg', '-y', '-i', video_path,
            '-filter_complex', filter_complex_arg,
            '-map', '[v]',        # Map the filtered video stream to the output
            '-map', '[a]',        # Map the copied audio stream to the output
            '-c:v', 'libx264',    # Specify the encoder for the video stream
            # We no longer need -c:a copy here, as it's handled by 'acopy' in the filter_complex
            '-preset', 'fast',
            '-crf', '22',
            output_path
        ]

        print("POST-PROCESS: Running ffmpeg command. This may take a while...")
        # For debugging, it can be helpful to see the full command
        # print(" ".join(command)) 
        result = subprocess.run(command, capture_output=True, text=True)

        if result.returncode == 0:
            print(f"POST-PROCESS: Successfully created processed video: {output_path}")
        else:
            print(f"POST-PROCESS: ERROR - ffmpeg failed to process the video.")
            print(f"         STDERR: {result.stderr}")

    except FileNotFoundError:
        print(f"POST-PROCESS: ERROR - Log file not found at {log_path}")
    except Exception as e:
        print(f"POST-PROCESS: An unexpected error occurred: {e}")