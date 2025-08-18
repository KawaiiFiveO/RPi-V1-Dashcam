# RPi-V1-Dashcam/controllers/oled_display.py

import time
import os.path
import socket
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306
from PIL import ImageFont

# Import shared application components
from shared_state import AppState
import config

class OledDisplay:
    """
    A controller that manages the OLED screen, displaying real-time status
    information by reading from the shared application state.
    """
    def __init__(self, state: AppState):
        """
        Initializes the OLED Display controller.
        Args:
            state: The shared application state object.
        """
        self.state = state
        self.device = None
        self.font_small = None
        self.font_large = None
        
        self.local_ip = "Checking..."
        self.last_ip_check_time = 0
        self.ip_check_interval = 10 # Check for a new IP every 10 seconds

        try:
            # Initialize the I2C interface for the OLED
            serial = i2c(port=config.OLED_I2C_PORT, address=config.OLED_I2C_ADDRESS)
            
            # Initialize the ssd1306 device with the correct dimensions
            self.device = ssd1306(serial, width=config.OLED_WIDTH, height=config.OLED_HEIGHT)
            
            # Load fonts
            self.font_small = self._get_font('pixelmix.ttf', 8)
            self.font_medium = self._get_font('pixelmix.ttf', 16)
            self.font_large = self._get_font('pixelmix.ttf', 24) # For prominent info

            print("OLEDDISPLAY: Initialized successfully.")
            # Briefly show a startup message
            with canvas(self.device) as draw:
                draw.text((18, 10), "Dashcam Starting...", font=self.font_small, fill="white")
            time.sleep(2)

        except Exception as e:
            print(f"OLEDDISPLAY: Error initializing display: {e}")
            print("OLEDDISPLAY: Will not be used. Please ensure I2C is enabled and the screen is connected.")
            self.device = None # Ensure device is None if setup fails

    def _get_local_ip(self):
        """Gets the local IP address of the device."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # This address doesn't have to be reachable
            s.connect(('10.255.255.255', 1))
            IP = s.getsockname()[0]
        except Exception:
            # If no route is found, it's likely in hotspot mode or connecting
            IP = '192.168.4.1' # Default to the known hotspot IP
        finally:
            s.close()
        return IP

    def _get_font(self, font_name: str, size: int):
        """Loads a font from the project's 'fonts' directory."""
        # This assumes a 'fonts' directory exists at the project root
        font_path = os.path.join(config.BASE_DIR, 'fonts', font_name)
        try:
            return ImageFont.truetype(font_path, size)
        except IOError:
            print(f"OLEDDISPLAY: Font '{font_name}' not found at '{font_path}'. Falling back to default.")
            return ImageFont.load_default()

    def _draw_alert_screen(self, draw):
        """Renders the display when a V1 alert is active."""
        v1_data = self.state.get_v1_data()

        # 1. Handle the main alert text (Frequency or Band)
        if v1_data.priority_alert_freq > 0:
            # Display frequency in large font for radar alerts
            main_text = f"{v1_data.priority_alert_freq:.3f}"
            band_text = v1_data.priority_alert_band
        else:
            # Display "Laser" in large font for laser alerts
            main_text = v1_data.priority_alert_band
            band_text = None # No smaller text needed for Laser

        # 2. Draw the large main text first, centered vertically
        # The y-coordinate is calculated to center the 24px font in the 32px high display
        draw.text((0, 4), main_text, font=self.font_large, fill="white")

        # 3. If there is smaller band text to draw (i.e., for radar)
        if band_text:
            # 3a. Calculate the width of the large text we just drew
            main_text_width = draw.textlength(main_text, font=self.font_large)
            
            # 3b. Define the position for the small text
            # x: to the right of the large text, with a 2px gap
            # y: aligned to the top of the large text
            band_text_x = main_text_width + 2
            band_text_y = 12

            # 3c. Draw the small band text
            draw.text((band_text_x, band_text_y), band_text, font=self.font_medium, fill="white")
            

    def _draw_normal_screen(self, draw):
        """Renders the default display screen."""
        v1_data = self.state.get_v1_data()
        gps_data = self.state.get_gps_data()
        web_status = self.state.get_web_server_status()

        # Line 1: V1 connection status
        if v1_data.is_connected:
            v1_status_text = f"V1: {v1_data.v1_mode}"
        else:
            v1_status_text = f"V1: {v1_data.connection_status}"
        draw.text((0, 0), v1_status_text, font=self.font_small, fill="white")

        # Line 2: GPS status and Speed
        if gps_data.has_fix:
            gps_status = f"GPS: {gps_data.num_sats} sats | {gps_data.speed_mph:.0f} MPH"
        else:
            gps_status = f"GPS: {gps_data.status}"
        draw.text((0, 8), gps_status, font=self.font_small, fill="white")

        # Line 3: GPS Coordinates
        if gps_data.has_fix:
            lat_lon_text = f"{gps_data.latitude:.5f}, {gps_data.longitude:.5f}"
            draw.text((0, 16), lat_lon_text, font=self.font_small, fill="white")
        else:
            # Show a placeholder if no fix
            draw.text((0, 16), "Lat/Lon: N/A", font=self.font_small, fill="white")
        
        # Line 4: Web Server Status (left-aligned) and Recording Status (right-aligned)
        if web_status == "Running":
            web_text = f"IP: {self.local_ip}"
        else:
            web_text = f"Web: {web_status}..."
        draw.text((0, 24), web_text, font=self.font_small, fill="white")

        if self.state.get_is_recording():
            rec_text = "REC ●"
        else:
            rec_text = "IDLE"
        # Calculate position for right alignment
        rec_text_width = draw.textlength(rec_text, font=self.font_small)
        draw.text((self.device.width - rec_text_width, 24), rec_text, font=self.font_small, fill="white")

    def run(self):
        """
        The main loop for the OLED display thread.
        Continuously redraws the screen with the latest data from the shared state.
        """
        # If the device failed to initialize, this thread does nothing.
        if not self.device:
            return

        while self.state.get_app_running():
            try:
                current_time = time.time()
                if current_time - self.last_ip_check_time > self.ip_check_interval:
                    self.local_ip = self._get_local_ip()
                    self.last_ip_check_time = current_time

                v1_data = self.state.get_v1_data()
                
                with canvas(self.device) as draw:
                    if v1_data.in_alert:
                        self._draw_alert_screen(draw)
                    else:
                        self._draw_normal_screen(draw)

                # Control the refresh rate of the display
                time.sleep(0.5)

            except Exception as e:
                print(f"OLEDDISPLAY: An error occurred in the display loop: {e}")
                time.sleep(5) # Wait a bit before retrying

        # Clear the display on shutdown
        try:
            self.device.clear()
        except Exception as e:
            print(f"OLEDDISPLAY: Could not clear display on exit: {e}")
            
        print("OLEDDISPLAY: Thread finished.")