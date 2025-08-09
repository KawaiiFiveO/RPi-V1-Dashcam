# RPi-V1-Dashcam/controllers/gps_reader.py

import serial
import pynmea2
import time

# Import shared application components
from shared_state import AppState, GpsData
import config

class GpsReader:
    """
    A controller that continuously reads from a serial GPS module,
    parses the NMEA data, and updates the shared application state.
    """
    def __init__(self, state: AppState):
        """
        Initializes the GPS Reader controller.
        Args:
            state: The shared application state object.
        """
        self.state = state
        self.serial_port = config.GPS_SERIAL_PORT
        self.baud_rate = config.GPS_BAUD_RATE

    def _update_state_no_fix(self):
        """Helper method to reset the GPS state when no fix is available."""
        current_gps_data = self.state.get_gps_data()
        if current_gps_data.has_fix:  # Only update if the state changes
            print("GPSREADER: Lost GPS fix.")
            self.state.set_gps_data(GpsData(has_fix=False))

    def run(self):
        """
        The main loop for the GPS reader thread.
        It attempts to connect to the serial port and read data until the
        application is shut down.
        """
        print(f"GPSREADER: Starting. Reading from {self.serial_port} at {self.baud_rate} baud.")

        while self.state.get_app_running():
            try:
                # The 'with' statement ensures the serial port is closed on exit
                with serial.Serial(self.serial_port, self.baud_rate, timeout=1) as ser:
                    print("GPSREADER: Serial port opened successfully.")
                    
                    # Let other components know we don't have a fix yet
                    self._update_state_no_fix()

                    current_gps_data = GpsData()

                    while self.state.get_app_running():
                        try:
                            line = ser.readline().decode('ascii', errors='replace').strip()
                            
                            if line.startswith('$GPGGA'):
                                msg = pynmea2.parse(line)
                                current_gps_data.has_fix = msg.gps_qual > 0
                                current_gps_data.latitude = msg.latitude or 0.0
                                current_gps_data.longitude = msg.longitude or 0.0
                                current_gps_data.altitude = msg.altitude or 0.0
                                current_gps_data.num_sats = int(msg.num_sats or 0)
                                # Update the shared state after parsing GGA
                                self.state.set_gps_data(current_gps_data)

                            elif line.startswith('$GPRMC'):
                                msg = pynmea2.parse(line)
                                # Speed is given in knots, convert to MPH (1 knot = 1.15078 MPH)
                                speed_knots = msg.spd_over_grnd or 0.0
                                current_gps_data.speed_mph = speed_knots * 1.15078
                                # Update the shared state after parsing RMC
                                self.state.set_gps_data(current_gps_data)


                        except pynmea2.ParseError:
                            # This is common if a sentence is corrupted or incomplete.
                            # We can safely ignore it and wait for the next one.
                            continue
                        except serial.SerialException:
                            # This can happen if the device is unplugged.
                            print("GPSREADER: Serial device disconnected. Attempting to reconnect...")
                            self._update_state_no_fix()
                            break # Exit inner loop to retry opening the port
                        except Exception as e:
                            print(f"GPSREADER: An unexpected error occurred while reading: {e}")
                            time.sleep(1)

            except serial.SerialException:
                # This catches errors when trying to open the serial port
                print(f"GPSREADER: Error opening serial port {self.serial_port}. Retrying in 5 seconds...")
                self._update_state_no_fix()
                time.sleep(5)
            
            except Exception as e:
                print(f"GPSREADER: A critical error occurred: {e}")
                self._update_state_no_fix()
                time.sleep(5)

        print("GPSREADER: Thread finished.")