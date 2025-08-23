# RPi-V1-Dashcam/web/app.py

import io
import os
import threading
from dataclasses import asdict
from threading import Condition
from typing import Optional

from flask import Flask, Response, render_template, jsonify, request, send_from_directory
from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput

# Import shared application components
from shared_state import AppState, StreamingOutput
import config

# The post_processing utility is imported here but will only be used by a background thread
from utils.post_processing import burn_in_data
from utils.log_analyzer import analyze_log_file

# Forward-declare the Recorder type for type hinting to avoid circular imports
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from controllers.recorder import Recorder

def create_app(state: Optional[AppState], picam2: Optional[Picamera2], recorder_controller: Optional['Recorder']):
    """
    Factory function to create the Flask application.
    This allows passing shared objects to the app and supports running in
    a 'web-only' mode if hardware-dependent objects are None.
    """
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.urandom(24)

    is_full_mode = all(obj is not None for obj in [state, picam2, recorder_controller])

    if is_full_mode:
        # --- FIX: Get the shared buffer from AppState ---
        streaming_output = state.get_streaming_output()
        
        def generate_frames():
            while True:
                with streaming_output.condition:
                    streaming_output.condition.wait()
                    frame = streaming_output.frame
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

        @app.route('/video_feed')
        def video_feed():
            return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

    @app.route('/')
    def index():
        return render_template('index.html', is_full_mode=is_full_mode)

    @app.route('/status')
    def status():
        """Provides a JSON object with the current application state."""
        if not is_full_mode:
            return jsonify({
                'recorder': {'is_recording': False},
                'v1': {'is_connected': False, 'in_alert': False, 'v1_mode': 'Offline', 'priority_alert_band': 'N/A', 'priority_alert_freq': 0.0, 'priority_alert_direction': 'N/A', 'priority_alert_strength': 0},
                'gps': {'has_fix': False, 'num_sats': 0},
                'overlays': {'show_gps': True, 'show_v1': True},
                'processing_files': []
            })
        
        return jsonify({
            'recorder': {'is_recording': state.get_is_recording()},
            'v1': asdict(state.get_v1_data()),
            'gps': asdict(state.get_gps_data()),
            'overlays': state.get_overlay_settings(),
            'processing_files': state.get_processing_files()
        })

    @app.route('/files')
    def list_files():
        try:
            video_files = sorted(
                [f for f in os.listdir(config.VIDEO_DIR) if f.endswith('.mp4')],
                reverse=True
            )
            file_list = []
            for f in video_files:
                base_name = f.replace('.mp4', '')
                log_name = f"{base_name}.csv"
                log_path = os.path.join(config.LOG_DIR, log_name)
                has_log = os.path.exists(log_path)

                # --- CALL THE ANALYZER ---
                analysis_results = analyze_log_file(log_path) if has_log else {
                    'has_alerts': False, 'alert_points': 0, 'total_points': 0
                }

                file_info = {
                    'name': f,
                    'size': f"{os.path.getsize(os.path.join(config.VIDEO_DIR, f)) / 1_000_000:.2f} MB",
                    'log_name': log_name,
                    'has_log': has_log,
                    'analysis': analysis_results # --- ADD RESULTS TO RESPONSE ---
                }
                file_list.append(file_info)
            return jsonify(file_list)
        except FileNotFoundError:
            return jsonify([])

    @app.route('/download/video/<path:filename>')
    def download_video(filename):
        return send_from_directory(config.VIDEO_DIR, filename, as_attachment=True)

    @app.route('/download/log/<path:filename>')
    def download_log(filename):
        return send_from_directory(config.LOG_DIR, filename, as_attachment=True)

    @app.route('/actions/start_recording', methods=['POST'])
    def action_start_recording():
        if not is_full_mode:
            return jsonify({'message': 'Cannot start recording in web-only mode.'}), 403
        if recorder_controller.start_recording():
            return jsonify({'message': 'Recording started successfully.'}), 200
        else:
            return jsonify({'message': 'Could not start recording (already running).'}), 409

    @app.route('/actions/stop_recording', methods=['POST'])
    def action_stop_recording():
        if not is_full_mode:
            return jsonify({'message': 'Cannot stop recording in web-only mode.'}), 403
        if recorder_controller.stop_recording():
            return jsonify({'message': 'Recording stopped successfully.'}), 200
        else:
            return jsonify({'message': 'Could not stop recording (not running).'}), 409

    @app.route('/actions/set_overlays', methods=['POST'])
    def action_set_overlays():
        if not is_full_mode:
            return jsonify({'message': 'Cannot change settings in web-only mode.'}), 403
        data = request.get_json()
        show_gps = data.get('show_gps', True)
        show_v1 = data.get('show_v1', True)
        state.set_overlay_settings(show_gps=show_gps, show_v1=show_v1)
        return jsonify({'message': 'Overlay settings updated.'}), 200

    @app.route('/actions/set_rotation', methods=['POST'])
    def action_set_rotation():
        if not is_full_mode:
            return jsonify({'message': 'Cannot change settings in web-only mode.'}), 403
        data = request.get_json()
        rotation = data.get('rotation', 0)
        recorder_controller.set_rotation(int(rotation))
        return jsonify({'message': f'Camera rotation set to {rotation} degrees.'}), 200

    @app.route('/actions/burn_in', methods=['POST'])
    def action_burn_in():
        data = request.get_json()
        if not data or 'filename' not in data:
            return jsonify({'message': 'Invalid request. Filename missing.'}), 400
        
        filename = data['filename']
        video_path = os.path.join(config.VIDEO_DIR, filename)
        log_path = os.path.join(config.LOG_DIR, filename.replace('.mp4', '.csv'))
        
        if not os.path.exists(video_path) or not os.path.exists(log_path):
            return jsonify({'message': 'Video or log file not found.'}), 404

        # --- FIX: Create a wrapper function to manage state ---
        def burn_in_task_wrapper(video_path, log_path):
            output_filename = os.path.basename(video_path).replace('.mp4', '_processed.mp4')
            
            # Only manage state if in full mode
            if is_full_mode:
                state.add_processing_file(output_filename, 'burn_in')
            
            try:
                # Call the now-decoupled utility function
                burn_in_data(video_path, log_path)
            finally:
                # Only manage state if in full mode
                if is_full_mode:
                    state.remove_processing_file(output_filename)

        # Start the wrapper function in a thread
        thread = threading.Thread(target=burn_in_task_wrapper, args=(video_path, log_path))
        thread.daemon = True
        thread.start()
        
        return jsonify({'message': f'Burn-in process started for {filename}. A new file ending in "_processed.mp4" will be created.'}), 202
        
    @app.route('/actions/reconnect_v1', methods=['POST'])
    def action_reconnect_v1():
        if not is_full_mode:
            return jsonify({'message': 'Cannot reconnect in web-only mode.'}), 403
        
        print("WEB: Manual V1 reconnect requested.")
        state.set_v1_reconnect_request()
        return jsonify({'message': 'V1 reconnect signal sent. Check status for updates.'}), 202
        
    @app.route('/actions/shutdown_pi', methods=['POST'])
    def action_shutdown_pi():
        if not is_full_mode:
            return jsonify({'message': 'Cannot shut down in web-only mode.'}), 403

        def shutdown_task():
            """A task to run in a background thread."""
            print("WEB: Shutdown initiated from web interface.")
            
            # 1. Signal the main application to start its graceful shutdown
            state.set_app_running(False)
            
            # 2. Wait a few seconds for controllers to clean up
            print("WEB: Waiting 5 seconds for application cleanup...")
            time.sleep(5)
            
            # 3. Issue the OS shutdown command
            print("WEB: Issuing OS shutdown command.")
            os.system('sudo /sbin/shutdown now')

        # Run the shutdown sequence in a background thread
        # so we can immediately return a response to the user.
        shutdown_thread = threading.Thread(target=shutdown_task)
        shutdown_thread.start()

        return jsonify({'message': 'Shutdown initiated. The Pi will power off shortly.'}), 202

    return app