# RPi-V1-Dashcam/utils/log_analyzer.py

import pandas as pd
from typing import Dict, List

def analyze_log_file(log_path: str) -> Dict:
    """
    Analyzes a given CSV log file to find V1 alert data, including the
    types of bands encountered.

    Args:
        log_path: The full path to the CSV log file.

    Returns:
        A dictionary containing the analysis results:
        {
            'has_alerts': bool,
            'alert_points': int,
            'total_points': int,
            'bands': List[str]
        }
    """
    # --- Default return value for all failure cases ---
    default_result = {'has_alerts': False, 'alert_points': 0, 'total_points': 0, 'bands': []}

    try:
        df = pd.read_csv(log_path)
        if df.empty:
            return default_result

        total_points = len(df)
        default_result['total_points'] = total_points

        # Check if the required columns exist to avoid errors with old logs
        if 'v1_in_alert' not in df.columns or 'v1_band' not in df.columns:
            return default_result

        # Filter the DataFrame to only rows where an alert is active
        alert_df = df[df['v1_in_alert'] == True]
        alert_points = len(alert_df)
        has_alerts = alert_points > 0

        unique_bands = []
        if has_alerts:
            # Get the unique, non-"N/A" bands from the alert rows
            unique_bands = alert_df['v1_band'].unique().tolist()
            unique_bands = [band for band in unique_bands if band != 'N/A']

        return {
            'has_alerts': has_alerts,
            'alert_points': alert_points,
            'total_points': total_points,
            'bands': unique_bands # Add the list of unique bands
        }
    except FileNotFoundError:
        return default_result
    except Exception as e:
        print(f"ERROR: Could not analyze log file {log_path}: {e}")
        return default_result