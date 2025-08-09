# RPi-V1-Dashcam/shared_state.py

import threading
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class V1Data:
    """Holds the current state of the Valentine One detector."""
    is_connected: bool = False
    in_alert: bool = False
    priority_alert_freq: float = 0.0
    priority_alert_band: str = "N/A"
    v1_mode: str = "Standby"

@dataclass
class GpsData:
    """Holds the current state of the GPS module."""
    has_fix: bool = False
    latitude: float = 0.0
    longitude: float = 0.0
    altitude: float = 0.0
    num_sats: int = 0
    speed_mph: float = 0.0

class AppState:
    def __init__(self):
        self._lock = threading.Lock()
        
        self.v1_data = V1Data()
        self.gps_data = GpsData()
        
        self.app_running = True
        self.is_recording = False
        self.overlay_show_gps = True
        self.overlay_show_v1 = True

    # --- Getters (These are safe as they are read-only) ---
    def get_v1_data(self) -> V1Data:
        with self._lock:
            return self.v1_data
    # ... (other getters are the same) ...
    def get_gps_data(self) -> GpsData:
        with self._lock:
            return self.gps_data
    def get_is_recording(self) -> bool:
        with self._lock:
            return self.is_recording
    def get_app_running(self) -> bool:
        with self._lock:
            return self.app_running
    def get_overlay_settings(self) -> dict:
        with self._lock:
            return {'show_gps': self.overlay_show_gps, 'show_v1': self.overlay_show_v1}

    # --- Setters (Now more specific and atomic) ---
    def set_is_recording(self, status: bool):
        with self._lock:
            self.is_recording = status
    def set_app_running(self, running: bool):
        with self._lock:
            self.app_running = running
    def set_overlay_settings(self, show_gps: bool, show_v1: bool):
        with self._lock:
            self.overlay_show_gps = show_gps
            self.overlay_show_v1 = show_v1
    def set_gps_data(self, new_data: GpsData):
        with self._lock:
            self.gps_data = new_data

    # --- NEW ATOMIC UPDATE METHODS FOR V1 ---
    def set_v1_connection_status(self, is_connected: bool):
        """Atomically updates the V1 connection status and resets state on disconnect."""
        with self._lock:
            self.v1_data.is_connected = is_connected
            if not is_connected:
                # If we are disconnecting, reset all other V1 fields
                self.v1_data.in_alert = False
                self.v1_data.v1_mode = "Standby"
                self.v1_data.priority_alert_band = "N/A"
                self.v1_data.priority_alert_freq = 0.0

    def update_v1_alert_data(self, in_alert: bool, band: str, freq: float):
        """Atomically updates the V1 alert information."""
        with self._lock:
            self.v1_data.in_alert = in_alert
            self.v1_data.priority_alert_band = band
            self.v1_data.priority_alert_freq = freq

    def update_v1_mode(self, mode: str):
        """Atomically updates the V1's current mode."""
        with self._lock:
            # Only update the mode if not in an alert, to prevent overwriting alert status
            if not self.v1_data.in_alert:
                self.v1_data.v1_mode = mode

    def update_v1_laser_alert(self):
        """Atomically sets a laser alert."""
        with self._lock:
            self.v1_data.in_alert = True
            self.v1_data.priority_alert_band = "Laser"
            self.v1_data.priority_alert_freq = 0.0