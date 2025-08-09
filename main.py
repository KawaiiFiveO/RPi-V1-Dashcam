# RPi-V1-Dashcam/main.py

import threading
import time
import sys
from waitress import serve

# Import all application components
import config
from shared_state import AppState
from controllers.v1_controller import V1Controller
from controllers.gps_reader import GpsReader
from controllers.oled_display import OledDisplay
from controllers.recorder import Recorder
from web.app import create_app

def run_full_mode():
    """
    Runs the dashcam in full operational mode with all controllers.
    """
    print("--- V1 Dashcam Application Starting (Full Mode) ---")
    
    state = AppState()

    print("MAIN: Initializing controllers...")
    try:
        recorder = Recorder(state)
        v1_controller = V1Controller(state)
        gps_reader = GpsReader(state)
        oled_display = OledDisplay(state)
    except Exception as e:
        print(f"MAIN: FATAL - Error during controller initialization: {e}", file=sys.stderr)
        sys.exit(1)
    print("MAIN: Controllers initialized.")

    threads = {
        "recorder": threading.Thread(target=recorder.run, daemon=True),
        "v1": threading.Thread(target=v1_controller.run, daemon=True),
        "gps": threading.Thread(target=gps_reader.run, daemon=True),
        "oled": threading.Thread(target=oled_display.run, daemon=True),
    }

    for name, thread in threads.items():
        print(f"MAIN: Starting thread for {name}...")
        thread.start()

    web_app = create_app(state, recorder.picam2, recorder)
    
    # --- FIX: Run the web server in its own thread ---
    # This is crucial because serve() is a blocking call.
    http_server_thread = threading.Thread(
        target=lambda: serve(web_app, host=config.WEB_SERVER_HOST, port=config.WEB_SERVER_PORT),
        daemon=True
    )
    http_server_thread.start()
    
    print(f"MAIN: Web server started on http://{config.WEB_SERVER_HOST}:{config.WEB_SERVER_PORT}")
    print("--- Application is now running ---")
    print("Press Ctrl+C to shut down gracefully.")
    
    try:
        # The main thread will now block here, waiting for a shutdown signal.
        while state.get_app_running():
            if not all(t.is_alive() for t in threads.values()):
                print("MAIN: A critical controller thread has died. Shutting down.")
                break
            if not http_server_thread.is_alive():
                print("MAIN: The web server thread has died. Shutting down.")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nMAIN: Shutdown signal received. Cleaning up...")
    finally:
        # This block now runs on Ctrl+C OR if a thread dies
        state.set_app_running(False)
        
        print("MAIN: Signaling controllers to shut down...")
        if v1_controller:
            v1_controller.shutdown()
        if recorder:
            recorder.shutdown()
        
        print("MAIN: Waiting for all threads to join...")
        for name, thread in threads.items():
            thread.join(timeout=15.0)
            if thread.is_alive():
                print(f"MAIN: WARNING - {name} thread did not exit cleanly.")
        
        # The http_server_thread is a daemon, so it will exit automatically
        # when the main program exits. No need to join it.
        
        print("--- V1 Dashcam Application Shut Down ---")

def run_web_only_mode():
    """
    Runs the dashcam in a limited mode that only starts the web server
    for file management. No hardware controllers are started.
    """
    print("--- V1 Dashcam Application Starting (Web-Only Mode) ---")
    
    web_app = create_app(state=None, picam2=None, recorder_controller=None)
    
    print(f"MAIN: Starting web server on http://{config.WEB_SERVER_HOST}:{config.WEB_SERVER_PORT}")
    print("--- File management interface is now running ---")
    print("Press Ctrl+C to exit.")
    
    # In this mode, it's okay for serve() to block the main thread,
    # as there are no other controllers to manage.
    serve(web_app, host=config.WEB_SERVER_HOST, port=config.WEB_SERVER_PORT)

def main():
    """
    The main entry point for the V1 Dashcam application.
    Parses command-line arguments to decide which mode to run.
    """
    try:
        print("MAIN: Creating output directories...")
        config.VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        (config.BASE_DIR / "fonts").mkdir(exist_ok=True)
        print("MAIN: Directories created successfully.")
    except OSError as e:
        print(f"MAIN: FATAL - Could not create directories: {e}", file=sys.stderr)
        sys.exit(1)

    if '--web-only' in sys.argv:
        try:
            run_web_only_mode()
        except KeyboardInterrupt:
            print("\nMAIN: Web-only mode stopped.")
    else:
        run_full_mode() # The try/except for shutdown is now inside this function

    sys.exit(0)

if __name__ == "__main__":
    main()