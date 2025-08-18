#!/usr/bin/env python3
# RPi-V1-Dashcam/process_video.py

import argparse
import subprocess
import pandas as pd
from datetime import datetime
import tempfile
import os
from pathlib import Path
from typing import Optional

# --- Configuration ---
VIDSTAB_SHAKINESS = 5
VIDSTAB_ACCURACY = 15
VIDSTAB_SMOOTHING = 10

# --- Helper Functions ---

def find_system_font(font_name: str = "Roboto") -> Optional[str]:
    """
    Tries to find a common system font file.
    This makes the script more portable across different OSes.
    """
    if os.name == 'nt':  # Windows
        font_path = Path(os.environ.get("SystemRoot", "C:/Windows"), "Fonts", f"{font_name}-Regular.ttf")
        if font_path.exists():
            return font_path.as_posix()
    else:  # macOS / Linux
        common_paths = [
            f"/usr/share/fonts/truetype/roboto/{font_name}-Regular.ttf",
            "/usr/share/fonts/TTF/Roboto-Regular.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ]
        for path in common_paths:
            if Path(path).exists():
                return path
    return None

def sanitize_font_path_for_ffmpeg(path_str: str) -> str:
    """
    Sanitizes a font path for use in an ffmpeg filter string, especially for Windows.
    """
    if os.name == 'nt':
        # Convert to forward slashes and escape the drive colon
        return path_str.replace('\\', '/').replace(':', '\\:')
    return path_str

def _escape_ffmpeg_text(text: str) -> str:
    """
    Escapes special characters for use inside an ffmpeg drawtext literal text value.
    """
    if not text:
        return ""
    text = text.replace('\\', '\\\\\\\\')
    text = text.replace("'", r"\'")
    text = text.replace(',', r'\,')
    text = text.replace('[', r'\[')
    text = text.replace(']', r'\]')
    text = text.replace('%', r'\%')
    text = text.replace(':', r'\:')
    return text

def process_video(video_path: Path, log_path: Path, output_path: Path, font_path: str, stabilize: bool):
    """
    Orchestrates the entire stabilization and burn-in process.
    """
    print(f"Processing video: {video_path.name}")
    print(f"Using log file: {log_path.name}")
    print(f"Output will be: {output_path.name}")
    print(f"Using font: {font_path}")
    print(f"Stabilization: {'Enabled' if stabilize else 'Disabled'}")

    filter_script_file = None
    transforms_file = None

    try:
        # --- Step 1: (Optional) vidstabdetect pass ---
        if stabilize:
            print("\n--- Step 1/3: Detecting camera shake... ---")
            # --- FIX: Create the transforms file in the same directory as the video ---
            transforms_file = video_path.with_suffix('.trf')
            
            detect_command = [
                'ffmpeg', '-y', '-i', str(video_path),
                # --- FIX: Pass the simple filename to the filter ---
                '-vf', f'vidstabdetect=result={transforms_file.name}',
                '-f', 'null', '-'
            ]
            
            # --- FIX: Run the command from the video's directory ---
            # This ensures ffmpeg can find the input and write the .trf file easily.
            subprocess.run(detect_command, check=True, capture_output=True, text=True, cwd=video_path.parent)
            print(f"Shake detection complete. Transforms saved to {transforms_file.name}")

        # --- Step 2: Build the complex filter chain ---
        print("\n--- Step 2/3: Building overlay filter chain... ---")
        log_data = pd.read_csv(log_path, parse_dates=['timestamp'])
        if log_data.empty:
            raise ValueError("Log file is empty. Aborting.")

        start_time = log_data['timestamp'].iloc[0]
        filters = []
        
        # Sanitize the font path once, as it's an absolute path
        sanitized_font_path = sanitize_font_path_for_ffmpeg(font_path)

        if stabilize:
            # --- FIX: Pass the simple filename to the transform filter ---
            stabilize_filter = f"vidstabtransform=input={transforms_file.name}:zoom=0:smoothing={VIDSTAB_SMOOTHING}:crop=black"
            filters.append(stabilize_filter)

        # --- Use the sanitized font path in all drawtext filters ---
        for _, row in log_data.iterrows():
            time_offset = (row['timestamp'] - start_time).total_seconds()
            end_offset = time_offset + 0.2
            
            ts_text = row['timestamp'].strftime("%Y-%m-%d %H.%M.%S")
            filters.append(
                f"drawtext=fontfile='{sanitized_font_path}':text='{_escape_ffmpeg_text(ts_text)}':x=w-tw-10:y=10:fontsize=28:fontcolor=white:borderw=2:bordercolor=black@1:enable='between(t,{time_offset},{end_offset})'"
            )

            if row['latitude'] != 0.0:
                gps_text = f"GPS: {row['latitude']:.5f}, {row['longitude']:.5f} | Sats: {int(row['sats'])} | {row['speed_mph']:.0f} MPH"
                filters.append(
                    f"drawtext=fontfile='{sanitized_font_path}':text='{_escape_ffmpeg_text(gps_text)}':x=10:y=10:fontsize=28:fontcolor=white:borderw=2:bordercolor=black@1:enable='between(t,{time_offset},{end_offset})'"
                )

            if row['v1_in_alert']:
                direction_text = str(row['v1_direction'])
                #arrow_parts = ['▲' if 'F' in direction_text else '', '◆' if 'S' in direction_text else '', '▼' if 'R' in direction_text else '']
                #arrow_str = "".join(filter(None, arrow_parts))
                #full_direction_display = f"{arrow_str} {direction_text}" if arrow_str else direction_text
                full_direction_display = direction_text
                alert_text = f"V1 ALERT: {row['v1_band']} / {row['v1_freq_ghz']:.3f} GHz | Dir: {full_direction_display} | Str: {int(row['v1_strength'])}"
                filters.append(
                    f"drawtext=fontfile='{sanitized_font_path}':text='{_escape_ffmpeg_text(alert_text)}':x=10:y=h-th-10:fontsize=30:fontcolor=yellow:borderw=3:bordercolor=black@1:enable='between(t,{time_offset},{end_offset})'"
                )

        filter_chain = ",".join(filters)
        filter_complex_content = f"[0:v]{filter_chain}[v];[0:a]acopy[a]"

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', encoding='utf-8') as f:
            filter_script_file = f.name
            f.write(filter_complex_content)
        
        # --- Step 3: Run the final ffmpeg command ---
        print("\n--- Step 3/3: Applying filters and encoding video... ---")
        print("This may take a while.")
        
        transform_command = [
            'ffmpeg', '-y', '-i', str(video_path),
            '-filter_complex_script', filter_script_file,
            '-map', '[v]',
            '-map', '[a]',
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '22',
            str(output_path)
        ]
        
        # --- FIX: Run this command from the video's directory as well ---
        subprocess.run(transform_command, check=True, capture_output=True, text=True, cwd=video_path.parent)
        print(f"\nSuccess! Processed video saved to: {output_path}")

    except FileNotFoundError:
        print(f"\nERROR: Could not find log file at {log_path}")
    except subprocess.CalledProcessError as e:
        print("\n--- FFMPEG ERROR ---")
        print(f"ffmpeg command failed with return code {e.returncode}")
        print("STDERR:")
        print(e.stderr)
        print("--------------------")
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}")
    finally:
        # --- Cleanup ---
        if filter_script_file and os.path.exists(filter_script_file):
            os.remove(filter_script_file)
        if transforms_file and transforms_file.exists():
            transforms_file.unlink()
        print("Temporary files cleaned up.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Stabilize and burn-in data overlays for dashcam videos.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("input_video", help="Path to the input MP4 video file.")
    parser.add_argument(
        "-o", "--output",
        help="Path for the output video file.\n(default: adds '_processed' to the input file name)"
    )
    parser.add_argument(
        "-f", "--font",
        help="Path to the TTF font file to use for overlays.\n(default: tries to find Roboto or another system font)"
    )
    parser.add_argument(
        "--no-stabilize",
        action="store_true",
        help="Skip the video stabilization step to process faster."
    )
    args = parser.parse_args()

    # --- Prepare paths and arguments ---
    input_video_path = Path(args.input_video)
    if not input_video_path.exists():
        print(f"Error: Input video file not found at '{input_video_path}'")
        exit(1)

    log_path = input_video_path.with_suffix('.csv')
    if not log_path.exists():
        print(f"Error: Corresponding log file not found at '{log_path}'")
        exit(1)

    output_path = Path(args.output) if args.output else input_video_path.with_name(f"{input_video_path.stem}_processed.mp4")
    
    font_path = args.font
    if not font_path:
        font_path = find_system_font()
        if not font_path:
            print("Error: Could not find a default system font. Please specify one with the --font flag.")
            print("Example: --font 'C:/Windows/Fonts/Arial.ttf'")
            exit(1)

    # --- Run the main processing function ---
    process_video(input_video_path, log_path, output_path, font_path, not args.no_stabilize)