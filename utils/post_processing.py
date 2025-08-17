# RPi-V1-Dashcam/utils/post_processing.py

import subprocess
import pandas as pd
from datetime import datetime
import tempfile
import os

# Import config to get the logging interval for the overlay duration
import config
from shared_state import AppState

def _escape_ffmpeg_text(text: str) -> str:
    """
    Escapes special characters for use inside an ffmpeg drawtext literal text value.
    This is for pre-rendered strings only (no %{...} expressions).
    """
    if not text:
        return text

    text = text.replace('\\', '\\\\\\\\')  # backslashes
    text = text.replace("'", r"\'")        # single quotes
    text = text.replace(',', r'\,')        # commas
    text = text.replace('[', r'\[')        # brackets
    text = text.replace(']', r'\]')
    text = text.replace('%', r'\%')        # percent signs (rare but safe to escape)
    text = text.replace(':', r'\:')        # colons (shouldn't be in new format, but just in case)
    return text


def burn_in_data(video_path: str, log_path: str):
    """
    Reads a CSV log file and burns the data as a text overlay onto the
    corresponding video file using ffmpeg. This version uses a complex filtergraph
    script to correctly handle video filtering alongside audio stream copying.
    """
    print(f"POST-PROCESS: Starting burn-in for {video_path}")
    
    filter_script_file = None
    output_filename = os.path.basename(video_path).replace('.mp4', '_processed.mp4')
    
    # --- Signal start of processing ---
    #app_state.add_processing_file(output_filename, 'burn_in')
    try:
        log_data = pd.read_csv(log_path, parse_dates=['timestamp'])
        if log_data.empty:
            print("POST-PROCESS: Log file is empty. Aborting.")
            return

        start_time = log_data['timestamp'].iloc[0]
        filters = []

        # Convert start_time to epoch seconds (int)
        timestamp_entries = log_data[['timestamp']].copy()
        
        for _, row in timestamp_entries.iterrows():
            time_offset = (row['timestamp'] - start_time).total_seconds()
            end_offset = time_offset + config.LOGGING_INTERVAL_SECONDS
            # No colons, just to keep ffmpeg parser happy
            ts_text = row['timestamp'].strftime("%Y-%m-%d %H.%M.%S")
            escaped_ts = _escape_ffmpeg_text(ts_text)
        
            filters.append(
                f"drawtext=font='Roboto':"
                f"text='{escaped_ts}':"
                f"x=w-tw-10:y=10:"
                f"fontsize=28:fontcolor=white:"
                f"borderw=2:bordercolor=black@1:"
                f"enable='between(t,{time_offset},{end_offset})'"
            )
        
        #filters.append(timestamp_filter)
        
        # --- Filter for GPS Data (This one correctly keeps the quotes for literal text) ---
        gps_entries = log_data[log_data['latitude'] != 0.0]
        for _, row in gps_entries.iterrows():
            time_offset = (row['timestamp'] - start_time).total_seconds()
            end_offset = time_offset + config.LOGGING_INTERVAL_SECONDS
            gps_text = f"GPS: {row['latitude']:.5f}, {row['longitude']:.5f} | Sats: {int(row['sats'])} | {row['speed_mph']:.0f} MPH"
            escaped_gps_text = _escape_ffmpeg_text(gps_text)
            
            filters.append(
                f"drawtext=font='Roboto':"
                f"text='{escaped_gps_text}':"
                f"x=10:y=10:"
                f"fontsize=28:fontcolor=white:"
                f"borderw=2:bordercolor=black@1:"
                f"enable='between(t,{time_offset},{end_offset})'"
            )

        # --- Filter for V1 Alert Data (This one also correctly keeps the quotes) ---
        alert_entries = log_data[log_data['v1_in_alert'] == True]
        for _, row in alert_entries.iterrows():
            time_offset = (row['timestamp'] - start_time).total_seconds()
            end_offset = time_offset + config.LOGGING_INTERVAL_SECONDS
            
            # --- CONSTRUCT NEW ALERT TEXT ---
            # --- NEW: Generate direction arrows from the direction string ---
            direction_text = str(row['v1_direction']) # Ensure it's a string
            arrow_parts = []
            if 'F' in direction_text:
                arrow_parts.append('▲') # Up arrow for Front
            if 'S' in direction_text:
                arrow_parts.append('◆') # Diamond for Side
            if 'R' in direction_text:
                arrow_parts.append('▼') # Down arrow for Rear
            
            # Join the arrows, then add the original text
            arrow_str = "".join(arrow_parts)
            full_direction_display = f"{arrow_str} {direction_text}" if arrow_str else direction_text

            # --- CONSTRUCT ALERT TEXT with the new direction display ---
            alert_text = (
                f"V1 ALERT: {row['v1_band']} / {row['v1_freq_ghz']:.3f} GHz | "
                f"Dir: {full_direction_display} | Str: {int(row['v1_strength'])}"
            )
            escaped_alert_text = _escape_ffmpeg_text(alert_text)

            filters.append(
                f"drawtext=font='Roboto':"
                f"text='{escaped_alert_text}':"
                f"x=10:y=h-th-10:"
                f"fontsize=30:fontcolor=yellow:"
                f"borderw=3:bordercolor=black@1:"
                f"enable='between(t,{time_offset},{end_offset})'"
            )

        filter_chain = ",".join(filters)
        
        filter_complex_content = f"[0:v]{filter_chain}[v];[0:a]acopy[a]"

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', encoding='utf-8') as f:
            filter_script_file = f.name
            f.write(filter_complex_content)
        
        print(f"POST-PROCESS: Complex filter script written to {filter_script_file}")

        output_path = video_path.replace('.mp4', '_processed.mp4')
        
        command = [
            'ffmpeg', '-y', '-i', video_path,
            '-filter_complex_script', filter_script_file,
            '-map', '[v]',
            '-map', '[a]',
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '22',
            output_path
        ]

        print("POST-PROCESS: Running ffmpeg command. This may take a while...")
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
    finally:
        #app_state.remove_processing_file(output_filename)
        if filter_script_file and os.path.exists(filter_script_file):
            os.remove(filter_script_file)
            print(f"POST-PROCESS: Cleaned up temporary file {filter_script_file}")