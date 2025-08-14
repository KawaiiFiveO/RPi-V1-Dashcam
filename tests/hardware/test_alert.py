# RPi-V1-Dashcam/tests/hardware/test_alert.py
# Description: A script to test the OLED alert screen by cycling through dummy alerts.

import time
import threading
import sys
import os

# --- Add the project root to the Python path ---
# This is necessary for the script to find the other project modules.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)
# -------------------------------------------------

from shared_state import AppState, V1Data
from controllers.oled_display import OledDisplay
import config

def main():
    """
    Main function to run the alert test.
    """
    print("--- OLED Alert Screen Test ---")
    print("This script will cycle through K, Ka, and Laser alerts.")
    print("Press Ctrl+C to exit.")

    # 1. Initialize the shared state and the OLED controller
    state = AppState()
    oled = OledDisplay(state)

    # Check if the OLED was initialized successfully
    if not oled.device:
        print("\nERROR: OLED display not found. Aborting test.")
        print("Please ensure the display is connected and I2C is enabled.")
        return

    # 2. Start the OLED display controller in its own thread
    # The daemon=True flag ensures the thread will exit when the main script does.
    oled_thread = threading.Thread(target=oled.run, daemon=True)
    oled_thread.start()
    time.sleep(1) # Give the thread a moment to start up

    # 3. Define the alerts we want to test
    alerts_to_test = [
        {'band': 'K', 'freq': 24.123},
        {'band': 'Ka', 'freq': 34.725},
        {'band': 'Laser', 'freq': 0.0},
    ]

    try:
        # 4. Main loop to cycle through the alerts
        while True:
            for alert in alerts_to_test:
                print(f"\nDisplaying {alert['band']} alert...")
                
                # Create a V1Data object representing the alert state
                # We set is_connected to True to make the simulation realistic
                alert_state = V1Data(
                    is_connected=True,
                    connection_status="Connected",
                    in_alert=True,
                    priority_alert_band=alert['band'],
                    priority_alert_freq=alert['freq'],
                    priority_alert_direction="F/R", # Dummy direction
                    priority_alert_strength=8        # Dummy strength
                )
                
                # Atomically update the shared state. The OLED thread will see this
                # change on its next refresh cycle.
                # Note: We are directly setting the v1_data object for this test.
                # In the real app, this is done via multiple atomic calls.
                with state._lock:
                    state.v1_data = alert_state

                # Wait for 5 seconds so the alert is visible
                time.sleep(5)

            # After cycling, show the normal screen for a bit
            print("\nDisplaying normal screen...")
            with state._lock:
                state.v1_data = V1Data(is_connected=True, connection_status="Connected")
            time.sleep(5)

    except KeyboardInterrupt:
        print("\n\nShutdown signal received. Cleaning up...")
    finally:
        # 5. Cleanly shut down the application
        state.set_app_running(False)
        if oled_thread.is_alive():
            oled_thread.join()
        print("Test finished.")

if __name__ == "__main__":
    main()