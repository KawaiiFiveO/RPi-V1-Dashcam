# RPi-V1-Dashcam/utils/log_analyzer.py

import pandas as pd
from typing import Dict

def analyze_log_file(log_path: str) -> Dict:
    """
    Analyzes a given CSV log file to find V1 alert data.

    Args:
        log_path: The full path to the CSV log file.

    Returns:
        A dictionary containing the analysis results:
        {
            'has_alerts': bool,
            'alert_points': int,
            'total_points': int
        }
    """
    try:
        df = pd.read_csv(log_path)
        if df.empty:
            return {'has_alerts': False, 'alert_points': 0, 'total_points': 0}

        total_points = len(df)

        # Check if the alert column exists to avoid errors with old logs
        if 'v1_in_alert' not in df.columns:
            return {'has_alerts': False, 'alert_points': 0, 'total_points': total_points}

        # Count rows where v1_in_alert is True
        alert_points = len(df[df['v1_in_alert'] == True])
        has_alerts = alert_points > 0

        return {
            'has_alerts': has_alerts,
            'alert_points': alert_points,
            'total_points': total_points
        }
    except FileNotFoundError:
        # The log file doesn't exist for this video
        return {'has_alerts': False, 'alert_points': 0, 'total_points': 0}
    except Exception as e:
        # Handle other potential errors like malformed CSVs
        print(f"ERROR: Could not analyze log file {log_path}: {e}")
        return {'has_alerts': False, 'alert_points': 0, 'total_points': 0}