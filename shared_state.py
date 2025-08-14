# RPi-V1-Dashcam/shared_state.py

import threading
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class V1Data:
    """Holds the current state of the Valentine One detector."""
    is_connected: bool = False
    connection_status: str = "Disconnected" # Disconnected, Scanning, Connecting, Connected
    in_alert: bool = False
    in_alert: bool = False
    priority_alert_freq: float = 0.0
    priority_alert_band: str = "N/A"
    priority_alert_direction: str = "N/A"
    priority_alert_strength: int = 0
    priority_alert_front_strength: int = 0
    priority_alert_rear_strength: int = 0
    v1_mode: str = "Standby"

@dataclass
class GpsData:
    """Holds the current state of the GPS module."""
    has_fix: bool = False
    status: str = "Initializing"
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
        self._processing_files: List[Dict[str, str]] = []
        self.v1_reconnect_request = False
        self.web_server_status = "Starting" # Can be: Starting, Running, Restarting

    # --- Getters (unchanged) ---
    def get_v1_data(self) -> V1Data:
        with self._lock:
            return self.v1_data
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
    def get_processing_files(self) -> list[dict[str, str]]:
        with self._lock:
            # Return a copy to prevent external modification
            return list(self._processing_files)
    def get_and_clear_v1_reconnect_request(self) -> bool:
        with self._lock:
            request = self.v1_reconnect_request
            self.v1_reconnect_request = False
            return request
    def get_web_server_status(self) -> str:
        with self._lock:
            return self.web_server_status
    # --- Setters (updated) ---
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
    def set_v1_reconnect_request(self):
        with self._lock:
            self.v1_reconnect_request = True
    def set_web_server_status(self, status: str):
        with self._lock:
            self.web_server_status = status
    # --- ATOMIC UPDATE METHODS FOR V1 ---
    def set_v1_connection_status(self, is_connected: bool, status: str):
        """Atomically updates the V1 connection status."""
        with self._lock:
            self.v1_data.is_connected = is_connected
            self.v1_data.connection_status = status
            if not is_connected:
                self.v1_data.in_alert = False
                self.v1_data.v1_mode = "Standby"
                self.v1_data.priority_alert_band = "N/A"
                self.v1_data.priority_alert_freq = 0.0
                self.v1_data.priority_alert_direction = "N/A"
                self.v1_data.priority_alert_strength = 0
                self.v1_data.priority_alert_front_strength = 0
                self.v1_data.priority_alert_rear_strength = 0

    def update_v1_alert_data(self, in_alert: bool, band: str, freq: float, front_str: int, rear_str: int):
        """Atomically updates the core V1 alert information from the alert table."""
        with self._lock:
            self.v1_data.in_alert = in_alert
            self.v1_data.priority_alert_band = band
            self.v1_data.priority_alert_freq = freq
            self.v1_data.priority_alert_front_strength = front_str
            self.v1_data.priority_alert_rear_strength = rear_str
            if not in_alert:
                self.v1_data.priority_alert_direction = "N/A"
                self.v1_data.priority_alert_strength = 0

    def update_v1_mode(self, mode: str):
        with self._lock:
            if not self.v1_data.in_alert:
                self.v1_data.v1_mode = mode

    def update_v1_display_info(self, strength: int):
        """Atomically updates the V1 total strength (LEDs) from display data."""
        with self._lock:
            self.v1_data.priority_alert_strength = strength
            # --- NEW: Derive and set the direction here ---
            dirs = []
            # A signal is considered "front" if front is stronger than rear.
            if self.v1_data.priority_alert_front_strength > self.v1_data.priority_alert_rear_strength:
                dirs.append("F")
            # A signal is considered "rear" if rear is stronger than front.
            elif self.v1_data.priority_alert_rear_strength > self.v1_data.priority_alert_front_strength:
                dirs.append("R")
            # If they are equal (and not zero), it's a side alert.
            elif self.v1_data.priority_alert_front_strength > 0:
                dirs.append("S")
            
            self.v1_data.priority_alert_direction = "/".join(dirs) if dirs else "N/A"

    def set_v1_laser_alert(self, direction: str, strength: int):
        """Atomically sets a complete laser alert. Laser direction is from display data."""
        with self._lock:
            self.v1_data.in_alert = True
            self.v1_data.priority_alert_band = "Laser"
            self.v1_data.priority_alert_freq = 0.0
            self.v1_data.priority_alert_direction = direction # Laser direction is reliable
            self.v1_data.priority_alert_strength = strength
            self.v1_data.priority_alert_front_strength = 0 # Not applicable for laser
            self.v1_data.priority_alert_rear_strength = 0
            
    def add_processing_file(self, filename: str, process_type: str):
        with self._lock:
            if {'filename': filename, 'type': process_type} not in self._processing_files:
                self._processing_files.append({'filename': filename, 'type': process_type})
                print(f"APPSTATE: Added {filename} ({process_type}) to processing queue.")

    def remove_processing_file(self, filename: str):
        with self._lock:
            initial_len = len(self._processing_files)
            self._processing_files = [f for f in self._processing_files if f['filename'] != filename]
            if len(self._processing_files) < initial_len:
                print(f"APPSTATE: Removed {filename} from processing queue.")
                